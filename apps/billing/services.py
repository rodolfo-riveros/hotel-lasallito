"""Emisión, envío, notas, anticipos, baja y guías de remisión (RF-FAC-01 a RF-FAC-10, RNF-DIS-04).

La numeración se asigna dentro de la transacción con bloqueo de la serie, de modo que nunca se
repite ni se salta (sección 8.3). Cada comprobante se genera en XML UBL 2.1 con su hash y se envía
a la SUNAT simulada, que lo valida y devuelve la constancia (CDR). Si no hay conexión, queda
"pendiente" con su número y se reintenta. Las bajas, los resúmenes diarios y las guías de remisión
se responden con un ticket que se consulta después, como en SUNAT.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog, ExchangeRate
from apps.folio.models import Charge, Concept

from . import ubl
from .models import (
    CustomerDocType,
    DocType,
    Invoice,
    InvoiceLine,
    RemissionGuide,
    Series,
    SunatSubmission,
    SunatTicket,
)
from .sunat import VOID_DAYS, get_adapter
from .validators import amount_in_words, dni_is_valid, ruc_is_valid

CENT = Decimal("0.01")
ZERO = Decimal("0")
IGV_RATE = Decimal("0.18")
EXPORT_LEGEND = (
    "Operación de exportación de servicios de alojamiento a sujeto no domiciliado "
    "(Art. 33° num. 4 TUO Ley del IGV)."
)
ADVANCE_LEGEND = "Comprobante emitido por anticipo de reserva."
SIMULATION_LEGEND = "SIMULACIÓN, SIN VALOR TRIBUTARIO"


@dataclass
class Customer:
    doc_type: str
    doc: str
    name: str
    address: str = ""
    email: str = ""
    company: object = None


def q2(v) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


SERIES_CODES = {
    DocType.FACTURA: "F001",
    DocType.BOLETA: "B001",
    DocType.REMISSION: "T001",
}


def default_series(property_obj, doc_type, related_doc_type=None) -> Series:
    codes = {
        **SERIES_CODES,
        DocType.CREDIT_NOTE: "FC01" if related_doc_type == DocType.FACTURA else "BC01",
        DocType.DEBIT_NOTE: "FD01" if related_doc_type == DocType.FACTURA else "BD01",
    }
    series = Series.objects.filter(property=property_obj, doc_type=doc_type, is_active=True)
    if doc_type in (DocType.CREDIT_NOTE, DocType.DEBIT_NOTE):
        series = series.filter(code__startswith=codes[doc_type][0])
    found = series.first()
    if found is None:
        found = Series.objects.create(property=property_obj, doc_type=doc_type, code=codes[doc_type])
    return found


def validate_customer(property_obj, doc_type: str, customer: Customer, total: Decimal):
    """Validaciones previas, como hace un sistema de facturación real antes de enviar (sección 12)."""
    if doc_type == DocType.FACTURA:
        if customer.doc_type != CustomerDocType.RUC or not ruc_is_valid(customer.doc):
            raise ValidationError(_("La factura requiere un RUC válido de 11 dígitos."))
        if not customer.name.strip():
            raise ValidationError(_("Indique la razón social."))
    if doc_type == DocType.BOLETA:
        if customer.doc_type == CustomerDocType.RUC:
            raise ValidationError(_("Para clientes con RUC emita factura."))
        if total > property_obj.boleta_dni_threshold and (
            customer.doc_type == CustomerDocType.NONE or not customer.doc
        ):
            raise ValidationError(
                _("Las boletas mayores a S/ %(t)s requieren el documento del cliente.")
                % {"t": property_obj.boleta_dni_threshold}
            )
        if customer.doc_type == CustomerDocType.DNI and not dni_is_valid(customer.doc):
            raise ValidationError(_("El DNI debe tener 8 dígitos."))


def affectation_for(charge: Charge) -> str:
    if charge.tax_exempt:
        return InvoiceLine.Affectation.EXPORT
    if not charge.concept.is_taxable:
        return InvoiceLine.Affectation.EXEMPT
    return InvoiceLine.Affectation.TAXED


def _next_number(series: Series) -> int:
    locked = Series.objects.select_for_update().get(pk=series.pk)
    number = locked.next_number
    locked.next_number = number + 1
    locked.save(update_fields=["next_number"])
    return number


def _apply_totals(invoice: Invoice):
    """Totales, leyendas, deducción de anticipos y XML firmado (hash)."""
    lines = list(invoice.lines.all())
    taxed = sum((ln.base for ln in lines if ln.affectation == "10"), ZERO)
    exempt = sum((ln.base for ln in lines if ln.affectation in ("20", "30")), ZERO)
    export = sum((ln.base for ln in lines if ln.affectation == "40"), ZERO)
    igv = sum((ln.igv for ln in lines), ZERO)
    other = sum((ln.other for ln in lines), ZERO)
    total = sum((ln.total for ln in lines), ZERO)
    prepaid = ZERO
    for adv in invoice.advances.all():  # RF-FAC-06: anticipos deducidos del comprobante final
        prepaid += adv.total
        taxed -= adv.taxed_amount
        exempt -= adv.exempt_amount
        export -= adv.export_amount
        igv -= adv.igv
    if prepaid > total:
        raise ValidationError(_("Los anticipos superan el total del comprobante."))
    invoice.taxed_amount, invoice.exempt_amount, invoice.export_amount = taxed, exempt, export
    invoice.igv, invoice.other_charges = igv, other
    invoice.prepaid_amount, invoice.total = prepaid, total - prepaid
    legends = [{"code": "1000", "text": amount_in_words(invoice.total, invoice.currency)}]
    if invoice.export_amount or any(ln.affectation == "40" for ln in lines):
        legends.append({"code": "2005", "text": EXPORT_LEGEND})
    if invoice.is_advance:
        legends.append({"code": "ANT", "text": ADVANCE_LEGEND})
    if prepaid:
        legends.append(
            {
                "code": "ANT",
                "text": _("Se deducen anticipos por %(m)s %(a)s.") % {"m": invoice.currency, "a": prepaid},
            }
        )
    if invoice.is_simulated:
        legends.append({"code": "SIM", "text": SIMULATION_LEGEND})
    invoice.legends = legends
    invoice.save()
    invoice.xml, invoice.hash = ubl.invoice_xml(invoice)
    invoice.save(update_fields=["xml", "hash"])


def _exchange_rate(property_obj, currency) -> Decimal:
    if currency != "USD":
        return Decimal("1")
    fx = ExchangeRate.for_date("USD", property_obj.current_business_date())
    if fx is None:
        raise ValidationError(_("Registre el tipo de cambio del día."))
    return fx.sell


def _new_invoice(
    property_obj, doc_type, customer, *, folio=None, currency="PEN", rate=Decimal("1"), due_days=0, **extra
) -> Invoice:
    series = default_series(property_obj, doc_type)
    issue_date = property_obj.current_business_date()
    return Invoice.objects.create(
        property=property_obj,
        series=series,
        number=_next_number(series),
        doc_type=doc_type,
        issue_date=issue_date,
        due_date=issue_date + timedelta(days=due_days) if due_days else None,
        currency=currency,
        exchange_rate=rate,
        customer_doc_type=customer.doc_type,
        customer_doc=customer.doc,
        customer_name=customer.name,
        customer_address=customer.address,
        customer_email=customer.email,
        company=customer.company,
        folio=folio,
        is_paid=due_days == 0,
        **extra,
    )


def _lines_from_charges(invoice, charges, rate, with_reference=False):
    for c in charges:
        conv = (lambda v: q2(v / rate)) if invoice.currency == "USD" else q2
        base, igv, other = conv(c.taxable_base), conv(c.igv), conv(c.service_charge)
        total = base + igv + other
        ref = ""
        if with_reference and c.folio.reservation_id:
            r = c.folio.reservation
            ref = f" · {r.code} {r.guest.last_name}"
        InvoiceLine.objects.create(
            invoice=invoice,
            charge=c,
            description=f"{c.description} ({c.service_date:%d/%m/%Y}){ref}"[:255],
            quantity=c.quantity,
            unit_price=q2(total / c.quantity) if c.quantity else total,
            affectation=affectation_for(c),
            base=base,
            igv=igv,
            other=other,
            total=total,
        )
    Charge.objects.filter(pk__in=[c.pk for c in charges]).update(invoice=invoice)


def _invoiceable(qs):
    return [c for c in qs.select_related("concept", "folio__reservation__guest") if c.concept.is_invoiceable]


def _after_issue(invoice, user, send):
    audit.log(AuditLog.Action.CREATE, invoice, changes={"total": str(invoice.total)}, user=user)
    if send:
        transaction.on_commit(lambda: send_invoice(Invoice.objects.get(pk=invoice.pk)))


def pending_advances(folio, doc_type, customer, currency):
    """Anticipos aceptados del folio que todavía no se descontaron (mismo cliente, tipo y moneda)."""
    return Invoice.objects.filter(
        folio=folio,
        is_advance=True,
        applied_to__isnull=True,
        doc_type=doc_type,
        currency=currency,
        customer_doc=customer.doc,
        status__in=[Invoice.Status.ACCEPTED, Invoice.Status.OBSERVED],
    )


@transaction.atomic
def issue_invoice(
    folio,
    doc_type: str,
    customer: Customer,
    *,
    user,
    charges=None,
    currency="PEN",
    due_days=0,
    send=True,
    apply_advances=True,
) -> Invoice:
    """RF-REC-10, RF-FAC-01: boleta o factura con los cargos no facturados del folio.

    Si el folio tiene comprobantes de anticipo, se deducen (RF-FAC-06).
    """
    property_obj = folio.property
    if not user.has_pms_perm(property_obj, "billing.create"):
        raise PermissionDenied(_("No puede emitir comprobantes."))
    qs = Charge.objects.select_for_update().filter(folio=folio, is_void=False, invoice__isnull=True)
    if charges is not None:
        qs = qs.filter(pk__in=[c.pk for c in charges])
    selected = _invoiceable(qs)
    if not selected:
        raise ValidationError(_("No hay cargos pendientes de facturar."))
    gross = sum((c.amount for c in selected), ZERO)
    if gross <= 0:
        raise ValidationError(_("El total a facturar debe ser mayor que cero."))
    advances = list(pending_advances(folio, doc_type, customer, currency)) if apply_advances else []
    validate_customer(property_obj, doc_type, customer, gross - sum((a.total for a in advances), ZERO))
    rate = _exchange_rate(property_obj, currency)
    invoice = _new_invoice(
        property_obj, doc_type, customer, folio=folio, currency=currency, rate=rate, due_days=due_days
    )
    _lines_from_charges(invoice, selected, rate)
    if advances:
        Invoice.objects.filter(pk__in=[a.pk for a in advances]).update(applied_to=invoice)
    _apply_totals(invoice)
    _after_issue(invoice, user, send)
    return invoice


def deposits_available(folio) -> Decimal:
    """Adelantos cobrados en el folio que aún no tienen comprobante de anticipo."""
    paid = sum((p.amount for p in folio.payments.filter(is_deposit=True, is_void=False)), ZERO)
    invoiced = sum(
        (
            i.total * i.exchange_rate
            for i in Invoice.objects.filter(folio=folio, is_advance=True).exclude(
                status__in=[Invoice.Status.REJECTED, Invoice.Status.VOIDED]
            )
        ),
        ZERO,
    )
    return q2(max(ZERO, paid - invoiced))


@transaction.atomic
def issue_advance(folio, doc_type, customer: Customer, amount, *, user, currency="PEN", send=True) -> Invoice:
    """RF-FAC-06: comprobante por el adelanto de una reserva (el IGV nace con el cobro anticipado)."""
    property_obj = folio.property
    if not user.has_pms_perm(property_obj, "billing.create"):
        raise PermissionDenied(_("No puede emitir comprobantes."))
    amount = q2(amount)
    rate = _exchange_rate(property_obj, currency)
    if amount <= 0:
        raise ValidationError(_("Indique el monto del anticipo."))
    if q2(amount * rate) > deposits_available(folio):
        raise ValidationError(
            _("El anticipo no puede superar los adelantos cobrados sin comprobante (S/ %(a)s).")
            % {"a": deposits_available(folio)}
        )
    validate_customer(property_obj, doc_type, customer, amount)
    reservation = folio.reservation
    exempt = bool(reservation and reservation.igv_exempt)
    invoice = _new_invoice(
        property_obj, doc_type, customer, folio=folio, currency=currency, rate=rate, is_advance=True
    )
    base = amount if exempt else q2(amount / (1 + IGV_RATE))
    code = reservation.code if reservation else folio.number
    InvoiceLine.objects.create(
        invoice=invoice,
        description=_("Anticipo de la reserva %(c)s") % {"c": code},
        unit_price=amount,
        affectation=InvoiceLine.Affectation.EXPORT if exempt else InvoiceLine.Affectation.TAXED,
        base=base,
        igv=amount - base,
        total=amount,
    )
    _apply_totals(invoice)
    _after_issue(invoice, user, send)
    return invoice


def grouped_charges(property_obj, company, start, end):
    """RF-FAC-06: cargos no facturados de una empresa o agencia en el periodo (estadías cerradas)."""
    from django.db.models import Q

    return (
        Charge.objects.filter(
            folio__property=property_obj,
            is_void=False,
            invoice__isnull=True,
            service_date__gte=start,
            service_date__lt=end,
            concept__is_invoiceable=True,
        )
        .filter(Q(folio__company=company) | Q(folio__reservation__company=company))
        .select_related("concept", "folio__reservation__guest")
        .order_by("folio__reservation__arrival", "service_date")
    )


@transaction.atomic
def issue_grouped_invoice(property_obj, company, charges, *, user, currency="PEN", due_days=None, send=True):
    """RF-FAC-06: una sola factura (a crédito) con los consumos de varias estadías de una empresa o agencia."""
    if not user.has_pms_perm(property_obj, "billing.create"):
        raise PermissionDenied(_("No puede emitir comprobantes."))
    ids = [c.pk for c in charges]
    selected = _invoiceable(
        Charge.objects.select_for_update().filter(
            pk__in=ids, folio__property=property_obj, is_void=False, invoice__isnull=True
        )
    )
    if not selected:
        raise ValidationError(_("No hay cargos pendientes de facturar."))
    customer = Customer(
        CustomerDocType.RUC, company.ruc, company.legal_name, company.address, company.email, company
    )
    gross = sum((c.amount for c in selected), ZERO)
    validate_customer(property_obj, DocType.FACTURA, customer, gross)
    rate = _exchange_rate(property_obj, currency)
    days = company.credit_days if due_days is None else due_days
    invoice = _new_invoice(
        property_obj, DocType.FACTURA, customer, currency=currency, rate=rate, due_days=days
    )
    _lines_from_charges(invoice, selected, rate, with_reference=True)
    _apply_totals(invoice)
    audit.log(
        AuditLog.Action.CREATE,
        invoice,
        changes={"total": str(invoice.total), "agrupada": len(selected)},
        user=user,
    )
    if send:
        transaction.on_commit(lambda: send_invoice(Invoice.objects.get(pk=invoice.pk)))
    return invoice


def send_invoice(invoice: Invoice) -> Invoice:
    """Envía el XML a la SUNAT simulada (o al OSE). Si no hay conexión, queda pendiente (RNF-DIS-04)."""
    if invoice.status in (Invoice.Status.VOIDED, Invoice.Status.VOIDING):
        return invoice
    if not invoice.xml:
        invoice.xml, invoice.hash = ubl.invoice_xml(invoice)
    result = get_adapter().send(invoice)
    SunatSubmission.objects.create(
        property=invoice.property,
        invoice=invoice,
        success=result.accepted,
        connection_error=result.connection_error,
        code=result.code,
        message=result.message[:255],
    )
    invoice.send_attempts += 1
    if result.accepted:
        invoice.status = Invoice.Status.OBSERVED if result.observations else Invoice.Status.ACCEPTED
    elif not result.connection_error:
        invoice.status = Invoice.Status.REJECTED
    invoice.sunat_code = result.code
    invoice.sunat_message = result.message[:255]
    invoice.observations = result.observations
    if result.cdr:
        invoice.cdr_xml = result.cdr
    invoice.save(
        update_fields=[
            "status",
            "sunat_code",
            "sunat_message",
            "send_attempts",
            "observations",
            "cdr_xml",
            "xml",
            "hash",
            "updated_at",
        ]
    )
    if invoice.status == Invoice.Status.REJECTED:
        # Un rechazo libera los cargos y anticipos para corregir y volver a emitir.
        Charge.objects.filter(invoice=invoice).update(invoice=None)
        Invoice.objects.filter(applied_to=invoice).update(applied_to=None)
    return invoice


def retry_pending(property_obj=None) -> int:
    qs = Invoice.objects.filter(status=Invoice.Status.PENDING)
    if property_obj:
        qs = qs.filter(property=property_obj)
    count = 0
    for invoice in qs.order_by("issue_date", "number"):
        send_invoice(invoice)
        count += invoice.status != Invoice.Status.PENDING
    return count


@transaction.atomic
def credit_note(original: Invoice, reason_code: str, reason: str, *, user, amount=None) -> Invoice:
    """RF-FAC-01: nota de crédito. Total (anulación) o parcial por monto."""
    if not user.has_pms_perm(original.property, "billing.void"):
        raise PermissionDenied(_("No puede emitir notas de crédito."))
    if original.doc_type not in (DocType.FACTURA, DocType.BOLETA):
        raise ValidationError(_("Solo se emiten notas sobre facturas o boletas."))
    if original.status not in (Invoice.Status.ACCEPTED, Invoice.Status.OBSERVED):
        raise ValidationError(_("El comprobante no está aceptado."))
    credited = sum(
        (n.total for n in original.notes.filter(doc_type=DocType.CREDIT_NOTE).exclude(status="rejected")),
        ZERO,
    )
    available = original.total - credited
    amount = q2(amount) if amount else available
    if amount <= 0 or amount > available:
        raise ValidationError(_("El monto supera el saldo del comprobante (%(a)s).") % {"a": available})
    series = default_series(original.property, DocType.CREDIT_NOTE, original.doc_type)
    note = Invoice.objects.create(
        property=original.property,
        series=series,
        number=_next_number(series),
        doc_type=DocType.CREDIT_NOTE,
        issue_date=original.property.current_business_date(),
        currency=original.currency,
        exchange_rate=original.exchange_rate,
        customer_doc_type=original.customer_doc_type,
        customer_doc=original.customer_doc,
        customer_name=original.customer_name,
        customer_address=original.customer_address,
        customer_email=original.customer_email,
        company=original.company,
        folio=original.folio,
        related_invoice=original,
        note_reason_code=reason_code,
        note_reason=reason,
    )
    full = amount == original.total and not credited and not original.prepaid_amount
    if full:
        for ln in original.lines.all():
            InvoiceLine.objects.create(
                invoice=note,
                description=ln.description,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                affectation=ln.affectation,
                base=ln.base,
                igv=ln.igv,
                other=ln.other,
                total=ln.total,
            )
        # Los cargos quedan libres para volver a facturar (ej. error en el RUC).
        Charge.objects.filter(invoice=original).update(invoice=None)
    else:
        taxed = original.taxed_amount > 0
        base = q2(amount / (1 + IGV_RATE)) if taxed else amount
        InvoiceLine.objects.create(
            invoice=note,
            description=reason or _("Descuento / devolución parcial"),
            unit_price=amount,
            affectation=(
                "10" if taxed else (original.lines.first().affectation if original.lines.exists() else "20")
            ),
            base=base,
            igv=amount - base,
            total=amount,
        )
    _apply_totals(note)
    audit.log(
        AuditLog.Action.VOID,
        note,
        changes={"modifica": original.full_number, "monto": str(amount)},
        reason=reason,
        user=user,
    )
    transaction.on_commit(lambda: send_invoice(Invoice.objects.get(pk=note.pk)))
    return note


@transaction.atomic
def debit_note(
    original: Invoice, reason_code: str, reason: str, amount, *, user, concept: Concept | None = None
):
    if not user.has_pms_perm(original.property, "billing.create"):
        raise PermissionDenied
    amount = q2(amount)
    if amount <= 0:
        raise ValidationError(_("Indique el monto de la nota de débito."))
    series = default_series(original.property, DocType.DEBIT_NOTE, original.doc_type)
    note = Invoice.objects.create(
        property=original.property,
        series=series,
        number=_next_number(series),
        doc_type=DocType.DEBIT_NOTE,
        issue_date=original.property.current_business_date(),
        currency=original.currency,
        customer_doc_type=original.customer_doc_type,
        customer_doc=original.customer_doc,
        customer_name=original.customer_name,
        customer_address=original.customer_address,
        folio=original.folio,
        related_invoice=original,
        note_reason_code=reason_code,
        note_reason=reason,
    )
    base = q2(amount / (1 + IGV_RATE))
    InvoiceLine.objects.create(
        invoice=note,
        description=reason,
        unit_price=amount,
        affectation="10",
        base=base,
        igv=amount - base,
        total=amount,
    )
    _apply_totals(note)
    audit.log(AuditLog.Action.CREATE, note, changes={"modifica": original.full_number}, user=user)
    transaction.on_commit(lambda: send_invoice(Invoice.objects.get(pk=note.pk)))
    return note


# --------------------------------------------------------------------------
# Baja (RA para facturas, resumen diario con estado 3 para boletas) — RF-FAC-10
# --------------------------------------------------------------------------


@transaction.atomic
def void_invoice(invoice: Invoice, reason: str, *, user) -> Invoice:
    """RF-FAC-10: comunicación de baja con plazo de 7 días, permisos y ticket de SUNAT."""
    if not user.has_pms_perm(invoice.property, "billing.void"):
        raise PermissionDenied(_("No puede dar de baja comprobantes."))
    if invoice.status in (Invoice.Status.VOIDED, Invoice.Status.VOIDING):
        raise ValidationError(_("El comprobante ya está dado de baja o en proceso de baja."))
    if not reason:
        raise ValidationError(_("Indique el motivo."))
    limit = invoice.issue_date + timedelta(days=VOID_DAYS)
    if invoice.property.current_business_date() > limit:
        raise ValidationError(
            _("Pasó el plazo de %(d)s días para la baja. Emita una nota de crédito.") % {"d": VOID_DAYS}
        )
    if invoice.status in (Invoice.Status.PENDING, Invoice.Status.REJECTED):
        # Nunca llegó a SUNAT: se anula en el sistema sin comunicación de baja.
        _finish_void(invoice, reason, "0", _("Anulado en el sistema: no fue informado a SUNAT"), user)
        return invoice
    adapter = get_adapter()
    if invoice.series.code.startswith("F"):
        result = adapter.send_voided(
            invoice.property,
            invoice.issue_date,
            [
                {
                    "doc_type": invoice.doc_type,
                    "series": invoice.series.code,
                    "number": invoice.number,
                    "reason": reason[:100],
                }
            ],
        )
    else:
        result = adapter.send_summary(invoice.property, invoice.issue_date, [_summary_item(invoice, "3")])
    SunatSubmission.objects.create(
        property=invoice.property,
        invoice=invoice,
        kind=SunatSubmission.Kind.VOID,
        success=result.accepted,
        connection_error=result.connection_error,
        code=result.code,
        message=result.message[:255],
        ticket=result.ticket,
    )
    if not result.ticket:
        raise ValidationError(_("SUNAT no respondió: %(m)s. Intente más tarde.") % {"m": result.message})
    invoice.status = Invoice.Status.VOIDING
    invoice.void_reason = reason
    invoice.save(update_fields=["status", "void_reason", "updated_at"])
    audit.log(AuditLog.Action.VOID, invoice, changes={"ticket": result.ticket}, reason=reason, user=user)
    transaction.on_commit(lambda: check_ticket(result.ticket))
    return invoice


def _finish_void(invoice, reason, code, message, user=None):
    invoice.status = Invoice.Status.VOIDED
    invoice.voided_at = timezone.now()
    invoice.void_reason = reason or invoice.void_reason
    invoice.sunat_code, invoice.sunat_message = code, str(message)[:255]
    invoice.save()
    Charge.objects.filter(invoice=invoice).update(invoice=None)
    Invoice.objects.filter(applied_to=invoice).update(applied_to=None)
    if user is not None:
        audit.log(AuditLog.Action.VOID, invoice, reason=invoice.void_reason, user=user)


def _summary_item(invoice, status):
    return {
        "doc_type": invoice.doc_type,
        "number": invoice.full_number,
        "receiver_doc_type": invoice.customer_doc_type,
        "receiver_doc": invoice.customer_doc,
        "total": invoice.total,
        "igv": invoice.igv,
        "taxed": invoice.taxed_amount,
        "currency": invoice.currency,
        "digest": invoice.hash,
        "status": status,
    }


def daily_summary(property_obj, day) -> SunatSubmission:
    """Resumen diario (RC): informa en bloque las boletas y notas B del día que quedaron pendientes."""
    pending = list(
        Invoice.objects.filter(
            property=property_obj, issue_date=day, status=Invoice.Status.PENDING, series__code__startswith="B"
        ).select_related("series")
    )
    if not pending:
        return SunatSubmission.objects.create(
            property=property_obj,
            kind=SunatSubmission.Kind.SUMMARY,
            success=True,
            code="0",
            message=_("No hay boletas pendientes de informar el %(d)s.") % {"d": day.strftime("%d/%m/%Y")},
        )
    for inv in pending:
        if not inv.xml:
            inv.xml, inv.hash = ubl.invoice_xml(inv)
            inv.save(update_fields=["xml", "hash"])
    result = get_adapter().send_summary(property_obj, day, [_summary_item(i, "1") for i in pending])
    sub = SunatSubmission.objects.create(
        property=property_obj,
        kind=SunatSubmission.Kind.SUMMARY,
        success=result.accepted,
        connection_error=result.connection_error,
        code=result.code,
        message=result.message[:255],
        ticket=result.ticket,
    )
    if result.ticket:
        check_ticket(result.ticket)
    return sub


# --------------------------------------------------------------------------
# Consulta de tickets (RC, RA y GRE)
# --------------------------------------------------------------------------


def check_ticket(number: str):
    """Consulta el ticket en SUNAT y aplica el resultado a los comprobantes o la guía."""
    ticket = SunatTicket.objects.filter(number=number).first()
    result = get_adapter().get_status(number)
    if result.processing or result.connection_error or ticket is None:
        return result
    if ticket.kind in (SunatTicket.Kind.VOID, SunatTicket.Kind.SUMMARY):
        for item in ticket.payload.get("items", []):
            series, num = (
                item["number"].split("-") if "-" in str(item["number"]) else (item["series"], item["number"])
            )
            inv = Invoice.objects.filter(
                property=ticket.property, doc_type=item["doc_type"], series__code=series, number=int(num)
            ).first()
            if inv is None:
                continue
            status = item.get("status", "3")
            if result.accepted and (ticket.kind == SunatTicket.Kind.VOID or status == "3"):
                _finish_void(inv, inv.void_reason, result.code, result.message)
                inv.cdr_xml = result.cdr
                inv.save(update_fields=["cdr_xml"])
            elif result.accepted and status == "1":
                inv.status, inv.sunat_code, inv.sunat_message = Invoice.Status.ACCEPTED, "0", result.message
                inv.cdr_xml = result.cdr
                inv.save(update_fields=["status", "sunat_code", "sunat_message", "cdr_xml"])
            elif inv.status == Invoice.Status.VOIDING:
                # SUNAT rechazó la baja: el comprobante sigue vigente.
                inv.status = Invoice.Status.ACCEPTED
                inv.sunat_code, inv.sunat_message = result.code, f"Baja rechazada: {result.message}"[:255]
                inv.save(update_fields=["status", "sunat_code", "sunat_message"])
    elif ticket.kind == SunatTicket.Kind.REMISSION:
        guide = RemissionGuide.objects.filter(ticket=ticket).first()
        if guide is not None:
            guide.status = (
                RemissionGuide.Status.ACCEPTED if result.accepted else RemissionGuide.Status.REJECTED
            )
            guide.sunat_code, guide.sunat_message = result.code, result.message[:255]
            guide.cdr_xml = result.cdr
            guide.save(update_fields=["status", "sunat_code", "sunat_message", "cdr_xml", "updated_at"])
    return result


def poll_tickets(property_obj=None) -> int:
    """Lo llama el programador de tareas: consulta los tickets en proceso."""
    qs = SunatTicket.objects.filter(status=SunatTicket.Status.PROCESSING, ready_at__lte=timezone.now())
    if property_obj:
        qs = qs.filter(property=property_obj)
    done = 0
    for t in qs:
        result = check_ticket(t.number)
        done += not result.processing
    return done


# --------------------------------------------------------------------------
# Guía de remisión remitente (RF-FAC-09)
# --------------------------------------------------------------------------


@transaction.atomic
def issue_guide(guide: RemissionGuide, *, user) -> RemissionGuide:
    """Numera la guía, genera su XML y la envía a SUNAT (responde con ticket)."""
    if not user.has_pms_perm(guide.property, "billing.create"):
        raise PermissionDenied(_("No puede emitir guías de remisión."))
    if guide.status not in (RemissionGuide.Status.DRAFT, RemissionGuide.Status.REJECTED):
        raise ValidationError(_("La guía ya fue enviada."))
    if not guide.lines.exists():
        raise ValidationError(_("Agregue al menos un bien a trasladar."))
    if guide.number is None or guide.status == RemissionGuide.Status.REJECTED:
        guide.number = _next_number(guide.series)
    guide.issue_date = guide.property.current_business_date()
    guide.save()
    guide.xml, guide.hash = ubl.despatch_xml(guide)
    result = get_adapter().send_despatch(guide)
    if not result.ticket:
        guide.status = RemissionGuide.Status.DRAFT
        guide.sunat_code, guide.sunat_message = result.code, result.message[:255]
        guide.save()
        raise ValidationError(_("SUNAT no respondió: %(m)s. Intente más tarde.") % {"m": result.message})
    guide.ticket = SunatTicket.objects.get(number=result.ticket)
    guide.status = RemissionGuide.Status.PROCESSING
    guide.sunat_code, guide.sunat_message = result.code, result.message[:255]
    guide.save()
    audit.log(AuditLog.Action.CREATE, guide, changes={"ticket": result.ticket}, user=user)
    transaction.on_commit(lambda: check_ticket(result.ticket))
    return guide


def new_guide(property_obj, **fields) -> RemissionGuide:
    today = property_obj.current_business_date()
    defaults = {
        "series": default_series(property_obj, DocType.REMISSION),
        "issue_date": today,
        "transfer_date": today,
        "origin_address": property_obj.address,
        "origin_ubigeo": property_obj.ubigeo,
    }
    defaults.update(fields)
    return RemissionGuide(property=property_obj, **defaults)


def customer_from_folio(folio, doc_type) -> Customer:
    """Datos sugeridos del cliente según el folio."""
    company = folio.company or (folio.reservation.company if folio.reservation else None)
    if doc_type == DocType.FACTURA and company:
        return Customer(
            CustomerDocType.RUC, company.ruc, company.legal_name, company.address, company.email, company
        )
    guest = folio.guest or (folio.reservation.guest if folio.reservation else None)
    if guest is None:
        return Customer(CustomerDocType.NONE, "", _("Clientes varios"))
    doc_type_map = {"1": CustomerDocType.DNI, "4": CustomerDocType.CE, "7": CustomerDocType.PASSPORT}
    return Customer(
        doc_type_map.get(guest.doc_type, CustomerDocType.NONE),
        guest.doc_number or "",
        guest.full_name,
        guest.address,
        guest.email,
    )
