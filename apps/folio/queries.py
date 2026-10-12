"""Saldos calculados en la misma consulta (evita N+1, RNF-REN-01)."""

from decimal import Decimal

from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .models import Charge, Payment

ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=12, decimal_places=2))


def _sum(model, **filters):
    return Coalesce(
        Subquery(
            model.objects.filter(is_void=False, **filters)
            .order_by()
            .values(next(iter(filters)))
            .annotate(s=Sum("amount"))
            .values("s")[:1],
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        ZERO,
    )


def with_reservation_balance(qs):
    return qs.annotate(
        charges_total=_sum(Charge, folio__reservation=OuterRef("pk")),
        payments_total=_sum(Payment, folio__reservation=OuterRef("pk")),
    )


def with_folio_balance(qs):
    return qs.annotate(
        charges_total=_sum(Charge, folio=OuterRef("pk")),
        payments_total=_sum(Payment, folio=OuterRef("pk")),
    )
