"""Indicadores y reportes (RF-REP-01 a RF-REP-05).

Definiciones (estándar de la industria):
- Habitaciones disponibles = habitaciones activas − bloqueadas, por noche.
- Habitaciones vendidas = reservas que ocupan una habitación esa noche.
- Ocupación = vendidas / disponibles.
- ADR = ingreso de alojamiento / vendidas.
- RevPAR = ingreso de alojamiento / disponibles  (= ocupación × ADR).

Para noches pasadas el ingreso sale de los cargos de alojamiento reales; para
noches futuras, de la tarifa pactada en cada reserva (pronóstico).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q, Sum

from apps.folio.models import Charge, Concept
from apps.reservations.models import Reservation
from apps.rooms.models import Room, RoomBlock

ZERO = Decimal("0")


def days(start: date, end: date):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def pct(a, b) -> Decimal:
    return (Decimal(a) * 100 / Decimal(b)).quantize(Decimal("0.1"), ROUND_HALF_UP) if b else Decimal("0.0")


def div(a, b) -> Decimal:
    return (Decimal(a) / Decimal(b)).quantize(Decimal("0.01"), ROUND_HALF_UP) if b else ZERO


@dataclass
class DayStats:
    date: date
    available: int
    sold: int
    revenue: Decimal

    @property
    def occupancy(self):
        return pct(self.sold, self.available)

    @property
    def adr(self):
        return div(self.revenue, self.sold)

    @property
    def revpar(self):
        return div(self.revenue, self.available)


def daily_stats(property_obj, start: date, end: date, room_type=None) -> list[DayStats]:
    rooms = Room.objects.filter(property=property_obj, is_active=True)
    if room_type is not None:
        rooms = rooms.filter(room_type=room_type)
    total_rooms = rooms.count()
    blocked = defaultdict(int)
    for b in RoomBlock.objects.filter(
        property=property_obj, is_active=True, start_date__lt=end, end_date__gt=start, room__in=rooms
    ):
        for d in days(max(b.start_date, start), min(b.end_date, end)):
            blocked[d] += 1
    today = property_obj.current_business_date()
    sold = defaultdict(int)
    forecast_rev = defaultdict(lambda: ZERO)
    res = Reservation.objects.filter(
        property=property_obj, status__in=Reservation.OCCUPYING_STATUSES, arrival__lt=end, departure__gt=start
    )
    if room_type is not None:
        res = res.filter(room_type=room_type)
    for r in res.only("arrival", "departure", "nightly_rates", "status", "currency"):
        for d in days(max(r.arrival, start), min(r.departure, end)):
            sold[d] += 1
            if d >= today:
                forecast_rev[d] += r.rate_for(d)
    actual_rev = defaultdict(lambda: ZERO)
    charges = Charge.objects.filter(
        folio__property=property_obj,
        is_void=False,
        concept__category=Concept.Category.LODGING,
        service_date__gte=start,
        service_date__lt=min(end, today),
    )
    if room_type is not None:
        charges = charges.filter(folio__reservation__room_type=room_type)
    for row in charges.values("service_date").annotate(s=Sum("amount")):
        actual_rev[row["service_date"]] = row["s"]
    return [
        DayStats(
            d,
            max(0, total_rooms - blocked[d]),
            sold[d],
            actual_rev[d] if d < today else forecast_rev[d],
        )
        for d in days(start, end)
    ]


def kpis(property_obj, start: date, end: date, room_type=None) -> dict:
    stats = daily_stats(property_obj, start, end, room_type)
    available = sum(s.available for s in stats)
    sold = sum(s.sold for s in stats)
    revenue = sum((s.revenue for s in stats), ZERO)
    return {
        "available": available,
        "sold": sold,
        "revenue": revenue,
        "occupancy": pct(sold, available),
        "adr": div(revenue, sold),
        "revpar": div(revenue, available),
        "days": stats,
    }


def revenue_by_area(property_obj, start, end):
    rows = (
        Charge.objects.filter(
            folio__property=property_obj, is_void=False, service_date__gte=start, service_date__lt=end
        )
        .values("concept__category")
        .annotate(total=Sum("amount"), n=Count("id"))
        .order_by("-total")
    )
    labels = dict(Concept.Category.choices)
    return [
        {"area": labels.get(r["concept__category"], r["concept__category"]), "total": r["total"], "n": r["n"]}
        for r in rows
    ]


def _stays(property_obj, start, end):
    return Reservation.objects.filter(
        property=property_obj, status__in=Reservation.OCCUPYING_STATUSES, arrival__gte=start, arrival__lt=end
    )


def revenue_by_channel(property_obj, start, end):
    """RF-REP-02: ingresos por canal y agencia (tarifa pactada de las llegadas del periodo)."""
    rows = defaultdict(lambda: {"reservations": 0, "nights": 0, "revenue": ZERO})
    labels = dict(Reservation.Channel.choices)
    for r in _stays(property_obj, start, end).select_related("company"):
        key = labels.get(r.channel, r.channel) + (f" · {r.company}" if r.company else "")
        rows[key]["reservations"] += 1
        rows[key]["nights"] += r.nights
        rows[key]["revenue"] += r.total_amount
    return sorted(({"channel": k, **v} for k, v in rows.items()), key=lambda x: -x["revenue"])


def guests_by_country(property_obj, start, end):
    """RF-REP-02: procedencia de huéspedes por país."""
    counter = Counter()
    nights = Counter()
    for r in _stays(property_obj, start, end).select_related("guest"):
        country = r.guest.residence_country.name or r.guest.nationality.name or "Sin dato"
        counter[country] += r.adults + r.children
        nights[country] += r.nights * (r.adults + r.children)
    return [{"country": c, "guests": n, "nights": nights[c]} for c, n in counter.most_common()]


def stay_stats(property_obj, start, end):
    qs = Reservation.objects.filter(property=property_obj, arrival__gte=start, arrival__lt=end)
    occupied = [
        r.nights for r in qs.filter(status__in=Reservation.OCCUPYING_STATUSES).only("arrival", "departure")
    ]
    return {
        "reservations": qs.count(),
        "alos": div(sum(occupied), len(occupied)),
        "cancelled": qs.filter(status=Reservation.Status.CANCELLED).count(),
        "no_show": qs.filter(status=Reservation.Status.NO_SHOW).count(),
        "cancellation_rate": pct(qs.filter(status=Reservation.Status.CANCELLED).count(), qs.count()),
    }


def forecast(property_obj, horizon_days=90):
    """RF-REP-04: pronóstico 30/60/90 días contra el mismo periodo del año anterior."""
    today = property_obj.current_business_date()
    result = []
    for n in (30, 60, 90):
        if n > horizon_days:
            break
        current = kpis(property_obj, today, today + timedelta(days=n))
        ly_start = today - timedelta(days=364)
        last_year = kpis(property_obj, ly_start, ly_start + timedelta(days=n))
        result.append(
            {
                "days": n,
                "occupancy": current["occupancy"],
                "adr": current["adr"],
                "revenue": current["revenue"],
                "ly_occupancy": last_year["occupancy"],
                "ly_revenue": last_year["revenue"],
                "delta": current["occupancy"] - last_year["occupancy"],
            }
        )
    return result


def mincetur_monthly(property_obj, year: int, month: int):
    """RF-REP-05: arribos y pernoctaciones por país de residencia (Encuesta Mensual de Establecimientos
    de Hospedaje, MINCETUR/DIRCETUR). Nacionales separados de extranjeros."""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    arrivals = Counter()
    overnight = Counter()
    res = Reservation.objects.filter(
        property=property_obj,
        status__in=[Reservation.Status.CHECKED_IN, Reservation.Status.CHECKED_OUT],
        arrival__lt=end,
        departure__gt=start,
    ).select_related("guest")
    for r in res:
        country = r.guest.residence_country.code or r.guest.nationality.code or "PE"
        pax = r.adults + r.children
        if start <= r.arrival < end:
            arrivals[country] += pax
        nights = len([d for d in days(max(r.arrival, start), min(r.departure, end))])
        overnight[country] += nights * pax
    from django_countries import countries

    rows = [
        {"code": c, "country": dict(countries).get(c, c), "arrivals": arrivals[c], "overnights": overnight[c]}
        for c in sorted(set(arrivals) | set(overnight), key=lambda x: (x != "PE", -overnight[x]))
    ]
    stats = kpis(property_obj, start, end)
    return {
        "rows": rows,
        "total_arrivals": sum(arrivals.values()),
        "total_overnights": sum(overnight.values()),
        "national_arrivals": arrivals["PE"],
        "foreign_arrivals": sum(v for k, v in arrivals.items() if k != "PE"),
        "occupancy": stats["occupancy"],
        "rooms_sold": stats["sold"],
        "start": start,
    }


def suggested_prices(property_obj, days_ahead=30):
    """RF-TAR-08: precio sugerido según la ocupación proyectada (reglas simples y explicables)."""
    from apps.rates.models import RatePlan
    from apps.rates.services import quote
    from apps.rooms.models import RoomType

    today = property_obj.current_business_date()
    plan = RatePlan.objects.filter(property=property_obj, kind=RatePlan.Kind.RACK, is_active=True).first()
    if plan is None:
        return []
    rows = []
    stats = {s.date: s for s in daily_stats(property_obj, today, today + timedelta(days=days_ahead))}
    rules = [
        (Decimal("90"), Decimal("20")),
        (Decimal("75"), Decimal("10")),
        (Decimal("40"), Decimal("0")),
        (Decimal("20"), Decimal("-10")),
        (Decimal("0"), Decimal("-15")),
    ]
    for rt in RoomType.objects.filter(property=property_obj, is_active=True):
        for d, s in stats.items():
            occ = s.occupancy
            adj = next(a for threshold, a in rules if occ >= threshold)
            q = quote(plan, rt, d, d + timedelta(days=1), adults=rt.base_occupancy, check_restrictions=False)
            if not q.ok:
                continue
            base = q.nights[0].amount
            rows.append(
                {
                    "date": d,
                    "room_type": rt,
                    "occupancy": occ,
                    "base": base,
                    "adjust": adj,
                    "suggested": property_obj.round_price(base * (100 + adj) / 100),
                }
            )
    return rows


def in_house(property_obj):
    from apps.folio.queries import with_reservation_balance

    return with_reservation_balance(
        Reservation.objects.filter(property=property_obj, status=Reservation.Status.CHECKED_IN)
        .select_related("guest", "room", "room_type", "rate_plan", "company")
        .order_by("room__number")
    )


def arrivals(property_obj, day):
    from apps.folio.queries import with_reservation_balance

    return with_reservation_balance(
        Reservation.objects.filter(
            property=property_obj, arrival=day, status__in=Reservation.PRE_ARRIVAL_STATUSES + ("checked_in",)
        )
        .select_related("guest", "room", "room_type", "rate_plan", "company")
        .order_by("eta", "code")
    )


def departures(property_obj, day):
    from apps.folio.queries import with_reservation_balance

    return with_reservation_balance(
        Reservation.objects.filter(
            property=property_obj, departure=day, status__in=["checked_in", "checked_out"]
        )
        .select_related("guest", "room", "room_type")
        .order_by("room__number")
    )


def free_rooms_today(property_obj):
    from apps.reservations.availability import free_rooms

    day = property_obj.current_business_date()
    return free_rooms(property_obj, day, day + timedelta(days=1)).order_by("room_type__name", "number")


def search_q(q):
    return Q(guest__first_name__icontains=q) | Q(guest__last_name__icontains=q) | Q(code__icontains=q)


def consolidated(properties, start, end):
    """RF-MUL-02: indicadores lado a lado por propiedad y total del grupo."""
    rows = []
    for prop in properties:
        k = kpis(prop, start, end)
        total = (
            Charge.objects.filter(
                folio__property=prop, is_void=False, service_date__gte=start, service_date__lt=end
            ).aggregate(s=Sum("amount"))["s"]
            or ZERO
        )
        rows.append(
            {
                "property": prop,
                "available": k["available"],
                "sold": k["sold"],
                "lodging": k["revenue"],
                "total": total,
                "occupancy": k["occupancy"],
                "adr": k["adr"],
                "revpar": k["revpar"],
                "in_house": Reservation.objects.filter(property=prop, status="checked_in").count(),
            }
        )
    available = sum(r["available"] for r in rows)
    sold = sum(r["sold"] for r in rows)
    lodging = sum((r["lodging"] for r in rows), ZERO)
    group = {
        "available": available,
        "sold": sold,
        "lodging": lodging,
        "total": sum((r["total"] for r in rows), ZERO),
        "occupancy": pct(sold, available),
        "adr": div(lodging, sold),
        "revpar": div(lodging, available),
        "in_house": sum(r["in_house"] for r in rows),
    }
    return rows, group
