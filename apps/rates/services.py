"""Motor de cotización (RF-TAR-01 a RF-TAR-05, RF-WEB-01).

`quote()` devuelve el precio noche por noche, valida restricciones (mínimo de
noches, cerrado a llegada / salida / venta, ocupación) y convierte de moneda
con el tipo de cambio del día. Todo en Decimal.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import DateRestriction, Promotion, RatePlan, RatePrice, Season

CENT = Decimal("0.01")


class QuoteError(Exception):
    pass


@dataclass
class NightPrice:
    date: date
    amount: Decimal
    season: str = ""


@dataclass
class Quote:
    rate_plan: RatePlan
    room_type: object
    arrival: date
    departure: date
    currency: str
    nights: list[NightPrice] = field(default_factory=list)
    discount_percent: Decimal = Decimal("0")
    promotion: Promotion | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        return sum((n.amount for n in self.nights), Decimal("0"))

    @property
    def discount(self) -> Decimal:
        return (self.subtotal * self.discount_percent / 100).quantize(CENT, ROUND_HALF_UP)

    @property
    def total(self) -> Decimal:
        return self.subtotal - self.discount

    @property
    def nightly(self) -> list[Decimal]:
        factor = (Decimal("100") - self.discount_percent) / 100
        return [(n.amount * factor).quantize(CENT, ROUND_HALF_UP) for n in self.nights]

    @property
    def ok(self) -> bool:
        return not self.errors

    def nightly_json(self) -> list[dict]:
        return [
            {"date": n.date.isoformat(), "amount": str(a)}
            for n, a in zip(self.nights, self.nightly, strict=True)
        ]


def daterange(start: date, end: date):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def season_for(property_obj, day: date, seasons=None):
    seasons = seasons if seasons is not None else Season.objects.filter(property=property_obj)
    matches = [s for s in seasons if s.start_date <= day <= s.end_date]
    return max(matches, key=lambda s: s.priority) if matches else None


def night_price(plan, room_type, day, adults, children=0, extra_beds=0, cribs=0, *, seasons=None, cache=None):
    """Precio de una noche en la moneda del plan (o del plan base)."""
    cache = cache if cache is not None else {}
    source = plan.base_plan or plan
    key = (source.pk, room_type.pk)
    if key not in cache:
        cache[key] = {p.season_id: p for p in RatePrice.objects.filter(rate_plan=source, room_type=room_type)}
    rows = cache[key]
    season = season_for(plan.property, day, seasons)
    row = rows.get(season.pk) if season else None
    row = row or rows.get(None)
    if row is None:
        raise QuoteError(
            _("No hay precio para %(type)s en el plan %(plan)s el %(day)s.")
            % {"type": room_type, "plan": source, "day": day.strftime("%d/%m/%Y")}
        )
    extra_adults = max(0, adults - room_type.base_occupancy)
    amount = (
        row.price
        + row.extra_adult * extra_adults
        + row.child * children
        + row.extra_bed * extra_beds
        + row.crib * cribs
    )
    if plan.base_plan_id:
        amount = amount * (Decimal("100") + plan.adjustment_percent) / 100
    return plan.property.round_price(amount.quantize(CENT, ROUND_HALF_UP)), season


def find_promotion(property_obj, code, plan, arrival, departure, today=None):
    if not code:
        return None
    today = today or timezone.localdate()
    promo = (
        Promotion.objects.filter(property=property_obj, code__iexact=code.strip(), is_active=True)
        .filter(valid_from__lte=today, valid_to__gte=today)
        .first()
    )
    if promo is None:
        return None
    if promo.max_uses is not None and promo.uses >= promo.max_uses:
        return None
    if promo.stay_from and arrival < promo.stay_from or promo.stay_to and departure > promo.stay_to:
        return None
    if (departure - arrival).days < promo.min_nights:
        return None
    if promo.rate_plans.exists() and not promo.rate_plans.filter(pk=plan.pk).exists():
        return None
    return promo


def quote(
    plan: RatePlan,
    room_type,
    arrival: date,
    departure: date,
    adults: int = 2,
    children: int = 0,
    extra_beds: int = 0,
    cribs: int = 0,
    *,
    currency: str | None = None,
    discount_percent: Decimal | None = None,
    promo_code: str = "",
    check_restrictions: bool = True,
) -> Quote:
    property_obj = plan.property
    plan_currency = (plan.base_plan or plan).currency_id
    q = Quote(
        rate_plan=plan, room_type=room_type, arrival=arrival, departure=departure, currency=plan_currency
    )
    nights = (departure - arrival).days
    if nights <= 0:
        q.errors.append(_("La salida debe ser posterior a la llegada."))
        return q
    if adults < 1:
        q.errors.append(_("Debe haber al menos un adulto."))
    if adults > room_type.max_adults or children > room_type.max_children:
        q.errors.append(_("La ocupación supera la capacidad de %(type)s.") % {"type": room_type})
    if adults + children > room_type.max_occupancy:
        q.errors.append(_("La ocupación supera la capacidad de %(type)s.") % {"type": room_type})

    seasons = list(
        Season.objects.filter(property=property_obj, end_date__gte=arrival, start_date__lt=departure)
    )
    cache = {}
    min_nights = plan.min_nights
    try:
        for day in daterange(arrival, departure):
            amount, season = night_price(
                plan, room_type, day, adults, children, extra_beds, cribs, seasons=seasons, cache=cache
            )
            if season:
                min_nights = max(min_nights, season.min_nights)
            q.nights.append(NightPrice(day, amount, season.name if season else ""))
    except QuoteError as exc:
        q.errors.append(str(exc))
        return q

    if check_restrictions:
        restrictions = DateRestriction.objects.filter(
            property=property_obj, date_from__lte=departure, date_to__gte=arrival
        ).filter(
            Q(room_type__isnull=True) | Q(room_type=room_type), Q(rate_plan__isnull=True) | Q(rate_plan=plan)
        )
        for r in restrictions:
            stay_days = [d for d in daterange(arrival, departure) if r.date_from <= d <= r.date_to]
            if r.stop_sell and stay_days:
                q.errors.append(_("Fechas cerradas a la venta: %(r)s") % {"r": r.reason or r})
            if r.closed_to_arrival and r.date_from <= arrival <= r.date_to:
                q.errors.append(_("No se permiten llegadas el %(d)s.") % {"d": arrival.strftime("%d/%m/%Y")})
            if r.closed_to_departure and r.date_from <= departure <= r.date_to:
                q.errors.append(_("No se permiten salidas el %(d)s.") % {"d": departure.strftime("%d/%m/%Y")})
            if r.min_nights and (stay_days or r.date_from <= arrival <= r.date_to):
                min_nights = max(min_nights, r.min_nights)
        if nights < min_nights:
            q.errors.append(_("La estadía mínima para estas fechas es de %(n)s noches.") % {"n": min_nights})

    promo = find_promotion(property_obj, promo_code, plan, arrival, departure)
    if promo:
        q.promotion = promo
        q.discount_percent = promo.discount_percent
    if discount_percent:
        q.discount_percent = Decimal(discount_percent)

    if currency and currency != plan_currency:
        convert_quote(q, currency)
    return q


def convert_quote(q: Quote, currency: str, on_date: date | None = None):
    """Convierte una cotización entre PEN y USD con el tipo de cambio de venta (RF-TAR-03)."""
    from apps.core.models import ExchangeRate

    rate = ExchangeRate.for_date("USD", on_date)
    if rate is None:
        q.errors.append(_("No hay tipo de cambio registrado."))
        return q
    for n in q.nights:
        if q.currency == "PEN" and currency == "USD":
            n.amount = (n.amount / rate.sell).quantize(CENT, ROUND_HALF_UP)
        elif q.currency == "USD" and currency == "PEN":
            n.amount = (n.amount * rate.sell).quantize(CENT, ROUND_HALF_UP)
    q.currency = currency
    return q
