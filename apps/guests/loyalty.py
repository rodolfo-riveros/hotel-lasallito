"""Programa de fidelidad (RF-HUE-04).

Los puntos se ganan al hacer check-out según el consumo en soles y el nivel del
socio, y se canjean como medio de pago en el folio. Es de la cadena: los puntos
ganados en un hotel se usan en cualquier otro (RF-MUL-03).
"""

from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog

from .models import Guest, LoyaltyTier, LoyaltyTransaction


def lifetime_points(guest: Guest) -> int:
    earned = (
        guest.loyalty_transactions.filter(points__gt=0)
        .exclude(kind=LoyaltyTransaction.Kind.ADJUST)
        .aggregate(s=Sum("points"))["s"]
    )
    return earned or 0


def tier_for(guest: Guest, lifetime: int | None = None) -> LoyaltyTier | None:
    lifetime = lifetime_points(guest) if lifetime is None else lifetime
    return LoyaltyTier.objects.filter(min_points__lte=lifetime).order_by("-min_points").first()


def _move(guest, property_obj, kind, points, description="", reservation=None) -> LoyaltyTransaction:
    tx = LoyaltyTransaction.objects.create(
        guest=guest,
        property=property_obj,
        kind=kind,
        points=points,
        description=description,
        reservation=reservation,
    )
    Guest.objects.filter(pk=guest.pk).update(loyalty_points=F("loyalty_points") + points)
    guest.refresh_from_db(fields=["loyalty_points"])
    return tx


@transaction.atomic
def award_stay_points(reservation, spent) -> LoyaltyTransaction | None:
    """Acumula puntos por el consumo de la estadía (se llama desde el check-out)."""
    guest = reservation.guest
    if not guest.email and not guest.phone:
        return None  # sin datos de contacto no es socio
    if LoyaltyTransaction.objects.filter(reservation=reservation, kind=LoyaltyTransaction.Kind.EARN).exists():
        return None
    tier = tier_for(guest)
    multiplier = tier.earn_multiplier if tier else Decimal("1")
    points = int(
        (Decimal(spent) * settings.LOYALTY_POINTS_PER_PEN * multiplier).to_integral_value(ROUND_DOWN)
    )
    if points <= 0:
        return None
    return _move(
        guest,
        reservation.property,
        LoyaltyTransaction.Kind.EARN,
        points,
        _("Estadía %(code)s") % {"code": reservation.code},
        reservation,
    )


def points_value(points: int) -> Decimal:
    return (Decimal(points) * settings.LOYALTY_PEN_PER_POINT).quantize(Decimal("0.01"))


@transaction.atomic
def redeem(guest: Guest, folio, points: int, user):
    """Canjea puntos como pago en el folio. Queda en auditoría."""
    from apps.folio.models import Payment
    from apps.folio.services import add_payment

    guest = Guest.objects.select_for_update().get(pk=guest.pk)
    if points <= 0:
        raise ValidationError(_("Indique los puntos a canjear."))
    if points > guest.loyalty_points:
        raise ValidationError(_("El huésped solo tiene %(n)s puntos.") % {"n": guest.loyalty_points})
    amount = points_value(points)
    if folio.balance is not None and amount > folio.balance:
        raise ValidationError(_("El canje (%(a)s) supera el saldo del folio.") % {"a": amount})
    payment = add_payment(folio, Payment.Method.POINTS, amount, user=user, reference=f"{points} pts")
    _move(
        guest,
        folio.property,
        LoyaltyTransaction.Kind.REDEEM,
        -points,
        _("Canje en folio %(f)s") % {"f": folio},
        folio.reservation,
    )
    audit.log(
        AuditLog.Action.DISCOUNT,
        payment,
        changes={"puntos": points, "importe": str(amount)},
        reason=_("Canje de puntos de fidelidad"),
        user=user,
        property=folio.property,
    )
    return payment


@transaction.atomic
def adjust(guest: Guest, property_obj, points: int, reason: str, user) -> LoyaltyTransaction:
    if not reason:
        raise ValidationError(_("Indique el motivo del ajuste."))
    tx = _move(guest, property_obj, LoyaltyTransaction.Kind.ADJUST, points, reason)
    audit.log(
        AuditLog.Action.UPDATE,
        guest,
        changes={"puntos": points},
        reason=reason,
        user=user,
        property=property_obj,
    )
    return tx
