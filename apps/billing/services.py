"""Emisión, envío, notas y baja de comprobantes (RF-FAC-01 a RF-FAC-10, RNF-DIS-04).

La numeración se asigna dentro de la transacción con bloqueo de la serie, de
modo que nunca se repite ni se salta (sección 8.3). Si SUNAT (o el simulador)
no responde, el comprobante queda "pendiente" con su número y se reintenta.
"""

import hashlib
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

from .models import CustomerDocType, DocType, Invoice, InvoiceLine, Series, SunatSubmission
from .sunat import get_adapter
from .validators import amount_in_words, dni_is_valid, ruc_is_valid

CENT = Decimal("0.01")
ZERO = Decimal("0")
EXPORT_LEGEND = (
    "Operación de exportación de servicios de alojamiento a sujeto no domiciliado "
    "(Art. 33° num. 4 TUO Ley del IGV)."
)
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


def default_series(property_obj, doc_type, related_doc_type=None) -> Series:
    codes = {
        DocType.FACTURA: "F001",
        DocType.BOLETA: "B001",
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
    """Mismas validaciones que en la realidad (sección 12)."""
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


def _hash(invoice) -> str:
    raw = f"{invoice.property.ruc}|{invoice.doc_type}|{invoice.full_number}|{invoice.total}|{invoice.issue_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:28]


def _next_number(series: Series) -> int:
    locked = Series.objects.select_for_update().get(pk=series.pk)
    number = locked.next_number
    locked.next_number = number + 1
    locked.save(update_fields=["next_number"])
    return number


def _apply_totals(invoice: Invoice):
    lines = list(invoice.lines.all())
    invoice.taxed_amount = sum((ln.base for ln in lines if ln.affectation == "10"), ZERO)
    invoice.exempt_amount = sum((ln.base for ln in lines if ln.affectation in ("20", "30")), ZERO)
    invoice.export_amount = sum((ln.base for ln in lines if ln.affectation == "40"), ZERO)
    invoice.igv = sum((ln.igv for ln in lines), ZERO)
    invoice.other_charges = sum((ln.other for ln in lines), ZERO)
    invoice.total = sum((ln.total for ln in lines), ZERO)
    legends = [{"code": "1000", "text": amount_in_words(invoice.total, invoice.currency)}]
    if invoice.export_amount:
        legends.append({"code": "2005", "text": EXPORT_LEGEND})
    if invoice.is_simulated:
        legends.append({"code": "SIM", "text": SIMULATION_LEGEND})
    invoice.legends = legends
    invoice.hash = _hash(invoice)
    invoice.save()


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
) -> Invoice:
    """RF-REC-10, RF-FAC-01: emite boleta o factura con los cargos no facturados del folio."""
    property_obj = folio.property
    if not user.has_pms_perm(property_obj, "billing.create"):
        raise PermissionDenied(_("No puede emitir comprobantes."))
    qs = Charge.objects.select_for_update().filter(folio=folio, is_void=False, invoice__isnull=True)
    if charges is not None:
        qs = qs.filter(pk__in=[c.pk for c in charges])
    selected = [c for c in qs.select_related("concept") if c.concept.is_invoiceable]
    if not selected:
        raise ValidationError(_("No hay cargos pendientes de facturar."))
    gross = sum((c.amount for c in selected), ZERO)
    if gross <= 0:
        raise ValidationError(_("El total a facturar debe ser mayor que cero."))
    validate_customer(property_obj, doc_type, customer, gross)
    rate = Decimal("1")
    if currency == "USD":
        fx = ExchangeRate.for_date("USD", property_obj.current_business_date())
        if fx is None:
            raise ValidationError(_("Registre el tipo de cambio del día."))
        rate = fx.sell
    series = default_series(property_obj, doc_type)
    issue_date = property_obj.current_business_date()
    invoice = Invoice.objects.create(
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
    )
    for c in selected:
        conv = (lambda v: q2(v / rate)) if currency == "USD" else q2
        base, igv, other = conv(c.taxable_base), conv(c.igv), conv(c.service_charge)
        total = base + igv + other
        InvoiceLine.objects.create(
            invoice=invoice,
            charge=c,
            description=f"{c.description} ({c.service_date:%d/%m/%Y})",
            quantity=c.quantity,
            unit_price=q2(total / c.quantity) if c.quantity else total,
            affectation=affectation_for(c),
            base=base,
            igv=igv,
            other=other,
            total=total,
        )
    Charge.objects.filter(pk__in=[c.pk for c in selected]).update(invoice=invoice)
    _apply_totals(invoice)
    audit.log(AuditLog.Action.CREATE, invoice, changes={"total": str(invoice.total)}, user=user)
    if send:
        transaction.on_commit(lambda: send_invoice(Invoice.objects.get(pk=invoice.pk)))
    return invoice


def send_invoice(invoice: Invoice) -> Invoice:
    """Envía al OSE/simulador. Si falla la conexión queda pendiente (RNF-DIS-04)."""
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
        invoice.status = Invoice.Status.ACCEPTED
    elif not result.connection_error:
        invoice.status = Invoice.Status.REJECTED
    invoice.sunat_code = result.code
    invoice.sunat_message = result.message[:255]
    invoice.save(update_fields=["status", "sunat_code", "sunat_message", "send_attempts", "updated_at"])
    if invoice.status == Invoice.Status.REJECTED:
        # Un rechazo libera los cargos para corregir y volver a emitir.
        Charge.objects.filter(invoice=invoice).update(invoice=None)
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
    credited = sum((n.total for n in original.notes.filter(doc_type=DocType.CREDIT_NOTE)), ZERO)
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
    full = amount == original.total and not credited
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
        base = q2(amount / Decimal("1.18")) if taxed else amount
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
        folio=original.folio,
        related_invoice=original,
        note_reason_code=reason_code,
        note_reason=reason,
    )
    base = q2(amount / Decimal("1.18"))
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


VOID_DAYS = 7


@transaction.atomic
def void_invoice(invoice: Invoice, reason: str, *, user) -> Invoice:
    """RF-FAC-10: baja con control de plazo (7 días) y permisos."""
    if not user.has_pms_perm(invoice.property, "billing.void"):
        raise PermissionDenied(_("No puede dar de baja comprobantes."))
    if invoice.status == Invoice.Status.VOIDED:
        raise ValidationError(_("El comprobante ya está dado de baja."))
    if not reason:
        raise ValidationError(_("Indique el motivo."))
    limit = invoice.issue_date + timedelta(days=VOID_DAYS)
    if invoice.property.current_business_date() > limit:
        raise ValidationError(
            _("Pasó el plazo de %(d)s días para la baja. Emita una nota de crédito.") % {"d": VOID_DAYS}
        )
    if invoice.status == Invoice.Status.PENDING:
        result_ok, code, msg = True, "0", "Baja local (no enviado)"
    else:
        result = get_adapter().void(invoice, reason)
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
        result_ok, code, msg = result.accepted, result.code, result.message
    if not result_ok:
        raise ValidationError(_("SUNAT no respondió: %(m)s. Intente más tarde.") % {"m": msg})
    invoice.status = Invoice.Status.VOIDED
    invoice.voided_at = timezone.now()
    invoice.void_reason = reason
    invoice.sunat_code, invoice.sunat_message = code, msg[:255]
    invoice.save()
    Charge.objects.filter(invoice=invoice).update(invoice=None)
    audit.log(AuditLog.Action.VOID, invoice, reason=reason, user=user)
    return invoice


def daily_summary(property_obj, day) -> SunatSubmission:
    """Resumen diario de boletas (simulado)."""
    boletas = Invoice.objects.filter(property=property_obj, issue_date=day, doc_type=DocType.BOLETA)
    result = get_adapter().daily_summary(property_obj, day, boletas)
    return SunatSubmission.objects.create(
        property=property_obj,
        kind=SunatSubmission.Kind.SUMMARY,
        success=result.accepted,
        connection_error=result.connection_error,
        code=result.code,
        message=result.message[:255],
        ticket=result.ticket,
    )


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
