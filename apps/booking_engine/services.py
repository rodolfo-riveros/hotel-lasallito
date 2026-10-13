"""Búsqueda y reserva en la web propia (RF-WEB-01 a 04)."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.models import ExchangeRate, Property
from apps.guests.models import Guest
from apps.rates.models import RatePlan
from apps.rates.services import Quote, quote
from apps.reservations import services as res
from apps.reservations.availability import availability_grid
from apps.reservations.models import Reservation
from apps.rooms.models import RoomType


def public_property(code: str | None = None) -> Property | None:
    qs = Property.objects.filter(is_active=True).order_by("pk")
    return (qs.filter(code=code).first() if code else None) or qs.first()


def currencies(property_obj) -> list[str]:
    """PEN siempre; USD si hay tipo de cambio registrado (RF-WEB-02)."""
    return ["PEN", "USD"] if ExchangeRate.for_date("USD", property_obj.current_business_date()) else ["PEN"]


@dataclass
class Offer:
    room_type: RoomType
    available: int
    quotes: list[Quote] = field(default_factory=list)

    @property
    def best(self):
        return min(self.quotes, key=lambda q: q.total) if self.quotes else None


def search(
    property_obj, arrival, departure, adults=2, children=0, *, currency="PEN", promo_code=""
) -> list[Offer]:
    """RF-WEB-01/02: tipos con disponibilidad y precio por plan público en la moneda elegida."""
    if departure <= arrival:
        raise ValidationError(_("La salida debe ser posterior a la llegada."))
    if arrival < property_obj.current_business_date():
        raise ValidationError(_("La llegada no puede ser una fecha pasada."))
    grid = availability_grid(property_obj, arrival, departure)
    plans = list(
        RatePlan.objects.filter(property=property_obj, is_active=True, is_public=True).select_related(
            "base_plan", "cancellation_policy"
        )
    )
    offers = []
    for rt in RoomType.objects.filter(property=property_obj, is_active=True).order_by("sort_order", "name"):
        free = min(grid.get(rt.pk, {arrival: 0}).values(), default=0)
        if free <= 0 or adults > rt.max_adults or adults + children > rt.max_occupancy:
            continue
        offer = Offer(rt, free)
        for plan in plans:
            q = quote(
                plan, rt, arrival, departure, adults, children, currency=currency, promo_code=promo_code
            )
            if q.ok:
                offer.quotes.append(q)
        if offer.quotes:
            offers.append(offer)
    return offers


@dataclass
class WebBooking:
    first_name: str
    last_name: str
    email: str
    phone: str = ""
    country: str = ""
    language: str = "es"
    special_requests: str = ""
    pay_online: bool = True
    extras: list = field(default_factory=list)  # [(Service, pax, date)]


@transaction.atomic
def book(
    property_obj,
    plan,
    room_type,
    arrival,
    departure,
    adults,
    children,
    data: WebBooking,
    *,
    currency="PEN",
    promo_code="",
) -> Reservation:
    """RF-WEB-03/04: crea la reserva web, su folio y los extras (upselling)."""
    from apps.tours.services import book_service

    guest = Guest.objects.filter(email__iexact=data.email).first()
    if guest is None:
        guest = Guest.objects.create(
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            phone=data.phone,
            nationality=data.country,
            residence_country=data.country,
            language=data.language,
        )
    reservation = res.create_reservation(
        property_obj,
        res.ReservationData(
            guest=guest,
            room_type=room_type,
            rate_plan=plan,
            arrival=arrival,
            departure=departure,
            adults=adults,
            children=children,
            channel=Reservation.Channel.WEB,
            currency=currency,
            promo_code=promo_code,
            status=Reservation.Status.PENDING if data.pay_online else Reservation.Status.CONFIRMED,
            special_requests=data.special_requests,
            notes=(
                _("Reserva web · pago en línea") if data.pay_online else _("Reserva web · paga en el hotel")
            ),
        ),
    )
    for service, pax, day in data.extras:
        book_service(service, date=day, pax=pax, reservation=reservation, notes=_("Extra de la web"))
    return reservation


def amount_due(reservation: Reservation) -> Decimal:
    """Alojamiento más los extras de la web, en la moneda de la reserva."""
    extras = sum((b.total for b in reservation.service_bookings.all()), Decimal("0"))
    if extras and reservation.currency == "USD":
        rate = ExchangeRate.for_date("USD", reservation.property.current_business_date())
        extras = (extras / rate.sell).quantize(Decimal("0.01")) if rate else Decimal("0")
    return reservation.total_amount + extras
