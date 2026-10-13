from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog

from .gateways import get_gateway
from .models import OnlinePayment


def create_payment(
    property_obj,
    amount,
    description,
    *,
    reservation=None,
    folio=None,
    email="",
    return_url="",
    currency="PEN",
    is_deposit=False,
) -> OnlinePayment:
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValidationError(_("El monto debe ser mayor que cero."))
    return OnlinePayment.objects.create(
        property=property_obj,
        provider=get_gateway().code,
        reservation=reservation,
        folio=folio,
        amount=amount,
        currency=currency,
        description=description,
        email=email,
        return_url=return_url,
        is_deposit=is_deposit,
    )


@transaction.atomic
def complete(payment: OnlinePayment, result) -> OnlinePayment:
    """Registra el resultado de la pasarela y, si se aprobó, el pago en el folio."""
    payment = OnlinePayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != OnlinePayment.Status.CREATED:
        return payment
    if not result.ok:
        payment.status = OnlinePayment.Status.FAILED
        payment.error = result.error[:200]
        payment.save()
        return payment
    payment.status = OnlinePayment.Status.PAID
    payment.provider_reference = result.reference
    payment.card_last4 = result.last4
    payment.card_brand = result.brand
    payment.save()
    folio = payment.folio
    if folio is None and payment.reservation is not None:
        from apps.folio.services import main_folio

        folio = main_folio(payment.reservation)
    if folio is not None:
        from apps.folio.models import Payment

        Payment.objects.create(
            folio=folio,
            date=folio.property.current_business_date(),
            method=Payment.Method.PAYMENT_LINK,
            currency=payment.currency,
            amount_original=payment.amount,
            amount=payment.amount,
            reference=f"{payment.provider} {payment.provider_reference} ****{payment.card_last4}",
            is_deposit=payment.is_deposit,
        )
    if payment.reservation is not None and payment.reservation.status == "pending":
        payment.reservation.status = "guaranteed"
        payment.reservation.guarantee = "card"
        payment.reservation.save(update_fields=["status", "guarantee"])
    audit.log(
        AuditLog.Action.CREATE, payment, changes={"monto": str(payment.amount)}, property=payment.property
    )
    return payment
