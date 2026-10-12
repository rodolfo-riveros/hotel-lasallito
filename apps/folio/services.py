"""Reglas del folio y la caja (RF-REC-09, RF-CAJ-01 a RF-CAJ-04, RF-TAR-06).

Los precios se cargan con impuestos incluidos. `split_taxes()` separa el valor
de venta, el IGV y el cargo por servicio según las reglas de impuestos de la
propiedad. El alojamiento de un huésped no domiciliado validado va exonerado
(exportación de servicios, RF-FAC-04).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog, ExchangeRate, Sequence, TaxRule

from .models import CashRegister, CashSession, Charge, Concept, Folio, Payment, PettyCashExpense

CENT = Decimal("0.01")
ZERO = Decimal("0")


def q2(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class TaxSplit:
    base: Decimal
    igv: Decimal
    service: Decimal
    exempt: bool


def split_taxes(property_obj, concept: Concept, amount: Decimal, exempt: bool = False) -> TaxSplit:
    amount = q2(amount)
    if not concept.is_taxable:
        return TaxSplit(amount, ZERO, ZERO, False)
    rules = list(
        TaxRule.objects.filter(property=property_obj, is_active=True).filter(
            applies_to__in=["all", concept.tax_category]
        )
    )
    igv_rate = sum((r.rate for r in rules if r.code == "igv"), ZERO)
    service_rate = sum((r.rate for r in rules if r.code != "igv"), ZERO)
    if exempt and concept.category == Concept.Category.LODGING:
        igv_rate = ZERO
    divisor = 1 + (igv_rate + service_rate) / 100
    base = q2(amount / divisor)
    service = q2(base * service_rate / 100)
    igv = amount - base - service
    return TaxSplit(base, igv, service, exempt and concept.category == Concept.Category.LODGING)


def next_folio_number(property_obj) -> str:
    return f"F{Sequence.next_value(property_obj, 'folio'):06d}"


def create_folio(
    property_obj, *, reservation=None, guest=None, company=None, name="", kind=Folio.Kind.GUEST, is_main=False
):
    return Folio.objects.create(
        property=property_obj,
        number=next_folio_number(property_obj),
        kind=kind,
        reservation=reservation,
        guest=guest,
        company=company,
        is_main=is_main,
        name=name or (str(company) if company else str(guest) if guest else _("Cuenta interna")),
    )


def main_folio(reservation) -> Folio:
    folio = reservation.folios.filter(is_main=True).first()
    if folio is None:
        folio = create_folio(
            reservation.property, reservation=reservation, guest=reservation.guest, is_main=True
        )
    return folio


def get_concept(property_obj, code: str) -> Concept:
    concept = Concept.objects.filter(property=property_obj, code=code).first()
    if concept is None:
        defaults = DEFAULT_CONCEPTS.get(code, (code, Concept.Category.SERVICES, True))
        concept = Concept.objects.create(
            property=property_obj,
            code=code,
            name=defaults[0],
            category=defaults[1],
            is_taxable=defaults[2],
            # Las propinas son del personal: no forman parte del comprobante.
            is_invoiceable=defaults[1] != Concept.Category.TIP,
        )
    return concept


DEFAULT_CONCEPTS = {
    "lodging": ("Alojamiento", Concept.Category.LODGING, True),
    "fnb": ("Restaurante y bar", Concept.Category.FNB, True),
    "minibar": ("Minibar", Concept.Category.MINIBAR, True),
    "laundry": ("Lavandería", Concept.Category.LAUNDRY, True),
    "oxygen": ("Oxígeno", Concept.Category.SERVICES, True),
    "tour": ("Tours", Concept.Category.TOURS, True),
    "transfer": ("Traslados", Concept.Category.TOURS, True),
    "penalty": ("Penalidad", Concept.Category.PENALTY, True),
    "early_checkin": ("Early check-in", Concept.Category.LODGING, True),
    "late_checkout": ("Late check-out", Concept.Category.LODGING, True),
    "tip": ("Propina", Concept.Category.TIP, False),
    "phone": ("Llamadas", Concept.Category.SERVICES, True),
}


@transaction.atomic
def post_charge(
    folio: Folio,
    concept: Concept,
    unit_price,
    *,
    quantity=1,
    description="",
    service_date=None,
    source=Charge.Source.MANUAL,
    reference="",
    exempt: bool | None = None,
    discount_percent=ZERO,
    user=None,
) -> Charge:
    if folio.status != Folio.Status.OPEN:
        raise ValidationError(_("El folio está cerrado."))
    quantity = Decimal(quantity)
    unit_price = q2(unit_price)
    gross = q2(unit_price * quantity * (100 - Decimal(discount_percent)) / 100)
    if exempt is None:
        exempt = bool(folio.reservation and folio.reservation.igv_exempt)
    split = split_taxes(folio.property, concept, gross, exempt)
    charge = Charge.objects.create(
        folio=folio,
        concept=concept,
        service_date=service_date or folio.property.current_business_date(),
        description=description or concept.name,
        quantity=quantity,
        unit_price=unit_price,
        amount=gross,
        taxable_base=split.base,
        igv=split.igv,
        service_charge=split.service,
        tax_exempt=split.exempt,
        source=source,
        reference=reference,
        discount_percent=discount_percent,
    )
    if Decimal(discount_percent) > 0:
        audit.log(
            AuditLog.Action.DISCOUNT,
            charge,
            changes={"descuento_%": str(discount_percent), "importe": str(gross)},
            property=folio.property,
        )
    return charge


@transaction.atomic
def void_charge(charge: Charge, reason: str, user) -> Charge:
    if not user.has_pms_perm(charge.folio.property, "folio.void"):
        raise PermissionDenied(_("No puede anular cargos."))
    if charge.invoice_id and charge.invoice.status not in ("voided",):
        raise ValidationError(_("El cargo ya tiene comprobante. Emita una nota de crédito."))
    if not reason:
        raise ValidationError(_("Indique el motivo."))
    charge.is_void = True
    charge.void_reason = reason
    charge.voided_at = timezone.now()
    charge.voided_by = user
    charge.save()
    audit.log(
        AuditLog.Action.VOID,
        charge,
        changes={"importe": str(charge.amount)},
        reason=reason,
        property=charge.folio.property,
    )
    return charge


@transaction.atomic
def transfer_charge(charge: Charge, target: Folio, user) -> Charge:
    """Mueve un cargo a otro folio (división de cuenta, RF-REC-09)."""
    if charge.invoice_id:
        raise ValidationError(_("No se puede transferir un cargo ya facturado."))
    if target.status != Folio.Status.OPEN or target.property_id != charge.folio.property_id:
        raise ValidationError(_("Folio de destino no válido."))
    origin = charge.folio
    charge.folio = target
    charge.save(update_fields=["folio", "updated_at"])
    audit.log(
        AuditLog.Action.UPDATE,
        charge,
        changes={"folio": [origin.number, target.number]},
        reason=_("Transferencia de cargo"),
        property=origin.property,
    )
    return charge


def open_session_for(user, property_obj):
    return CashSession.objects.filter(
        property=property_obj, user=user, status=CashSession.Status.OPEN
    ).first()


@transaction.atomic
def add_payment(
    folio: Folio,
    method: str,
    amount,
    *,
    user,
    currency="PEN",
    reference="",
    is_deposit=False,
    tip=ZERO,
    refund=False,
) -> Payment:
    """Registra un cobro (o devolución). El efectivo exige caja abierta (RF-CAJ-01)."""
    amount = q2(amount)
    if amount <= 0:
        raise ValidationError(_("El monto debe ser mayor que cero."))
    property_obj = folio.property
    session = open_session_for(user, property_obj)
    if method in Payment.CASH_METHODS and session is None:
        raise ValidationError(_("Abra su caja antes de cobrar en efectivo."))
    if method == Payment.Method.CASH_USD:
        currency = "USD"
    rate = Decimal("1")
    if currency == "USD":
        fx = ExchangeRate.for_date("USD", property_obj.current_business_date())
        if fx is None:
            raise ValidationError(_("Registre el tipo de cambio del día."))
        rate = fx.buy  # el hotel compra los dólares que recibe
    amount_pen = q2(amount * rate)
    if method == Payment.Method.CITY_LEDGER:
        company = folio.company or (folio.reservation.company if folio.reservation else None)
        if company is None or company.credit_limit <= 0:
            raise ValidationError(_("Solo empresas con línea de crédito pueden pagar a cuenta corriente."))
    sign = -1 if refund else 1
    payment = Payment.objects.create(
        folio=folio,
        date=property_obj.current_business_date(),
        method=method,
        currency=currency,
        amount_original=amount * sign,
        exchange_rate=rate,
        amount=amount_pen * sign,
        reference=reference,
        is_deposit=is_deposit,
        is_refund=refund,
        tip=q2(tip),
        cash_session=session,
    )
    if refund:
        audit.log(
            AuditLog.Action.VOID, payment, changes={"devolución": str(amount_pen)}, property=property_obj
        )
    return payment


@transaction.atomic
def void_payment(payment: Payment, reason: str, user) -> Payment:
    if not user.has_pms_perm(payment.folio.property, "folio.void"):
        raise PermissionDenied
    if payment.cash_session and payment.cash_session.status == CashSession.Status.CLOSED:
        raise ValidationError(_("El turno de caja ya está cerrado."))
    payment.is_void = True
    payment.void_reason = reason
    payment.save()
    audit.log(
        AuditLog.Action.VOID,
        payment,
        changes={"monto": str(payment.amount)},
        reason=reason,
        property=payment.folio.property,
    )
    return payment


@transaction.atomic
def close_folio(folio: Folio, user) -> Folio:
    if folio.balance != 0:
        raise ValidationError(_("El folio tiene saldo pendiente: %(s)s") % {"s": folio.balance})
    folio.status = Folio.Status.CLOSED
    folio.closed_at = timezone.now()
    folio.save()
    return folio


# --------------------------------------------------------------------------
# Caja
# --------------------------------------------------------------------------


@transaction.atomic
def open_cash_session(register: CashRegister, user, opening_pen=ZERO, opening_usd=ZERO) -> CashSession:
    if open_session_for(user, register.property):
        raise ValidationError(_("Ya tiene una caja abierta."))
    if CashSession.objects.filter(register=register, status=CashSession.Status.OPEN).exists():
        raise ValidationError(_("Esta caja ya está abierta por otro usuario."))
    return CashSession.objects.create(
        property=register.property,
        register=register,
        user=user,
        business_date=register.property.current_business_date(),
        opening_pen=q2(opening_pen),
        opening_usd=q2(opening_usd),
    )


def expected_by_method(session: CashSession) -> dict[str, Decimal]:
    """Esperado por medio de pago (en la moneda del medio)."""
    expected: dict[str, Decimal] = {m: ZERO for m, _label in Payment.Method.choices}
    for p in session.payments.filter(is_void=False):
        expected[p.method] += p.amount_original if p.method == Payment.Method.CASH_USD else p.amount
    expected[Payment.Method.CASH_PEN] += session.opening_pen
    expected[Payment.Method.CASH_USD] += session.opening_usd
    for e in session.expenses.all():
        expected[Payment.Method.CASH_PEN] -= e.amount
    return {k: q2(v) for k, v in expected.items()}


@transaction.atomic
def close_cash_session(session: CashSession, counted: dict, user, notes="") -> CashSession:
    """RF-CAJ-01/04: arqueo, diferencias y conciliación por medio de pago."""
    if session.status != CashSession.Status.OPEN:
        raise ValidationError(_("El turno ya está cerrado."))
    if session.user_id != user.pk and not user.has_pms_perm(session.property, "folio.approve"):
        raise PermissionDenied(_("Solo el cajero o un supervisor pueden cerrar el turno."))
    expected = expected_by_method(session)
    counted_clean = {k: q2(counted.get(k) or 0) for k in expected}
    fx = ExchangeRate.for_date("USD", session.business_date)
    usd_rate = fx.buy if fx else Decimal("1")
    diff = ZERO
    for method, exp in expected.items():
        if method in (
            Payment.Method.CASH_PEN,
            Payment.Method.CARD,
            Payment.Method.YAPE,
            Payment.Method.PLIN,
            Payment.Method.TRANSFER,
        ):
            diff += counted_clean[method] - exp
        elif method == Payment.Method.CASH_USD:
            diff += q2((counted_clean[method] - exp) * usd_rate)
    session.expected = {k: str(v) for k, v in expected.items()}
    session.counted = {k: str(v) for k, v in counted_clean.items()}
    session.difference = q2(diff)
    session.status = CashSession.Status.CLOSED
    session.closed_at = timezone.now()
    session.notes = notes
    session.save()
    audit.log(
        AuditLog.Action.CASH_CLOSE,
        session,
        changes={
            "esperado": session.expected,
            "contado": session.counted,
            "diferencia": str(session.difference),
        },
        reason=notes,
        property=session.property,
    )
    return session


def add_petty_expense(session: CashSession, description: str, amount, receipt="") -> PettyCashExpense:
    if session.status != CashSession.Status.OPEN:
        raise ValidationError(_("El turno está cerrado."))
    return PettyCashExpense.objects.create(
        session=session, description=description, amount=q2(amount), receipt=receipt
    )
