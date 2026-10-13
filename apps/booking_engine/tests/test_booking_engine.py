"""Motor de reservas web: RF-WEB-01 a RF-WEB-06."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.booking_engine import services
from apps.booking_engine.models import GroupRequest
from apps.payments.models import OnlinePayment
from apps.reservations.models import Reservation
from apps.tours.models import Service
from conftest import BUSINESS_DATE

ARRIVAL = BUSINESS_DATE + timedelta(days=2)
DEPARTURE = ARRIVAL + timedelta(days=2)


def _params(setup, **extra):
    return {
        "llegada": ARRIVAL.isoformat(),
        "salida": DEPARTURE.isoformat(),
        "adultos": 2,
        "ninos": 0,
        "moneda": "PEN",
        "tipo": setup.double.pk,
        "plan": setup.rack.pk,
        **extra,
    }


def _guest_data(**extra):
    return {
        "first_name": "Lucas",
        "last_name": "Oliveira",
        "email": "lucas@example.com",
        "phone": "+55 11 9",
        "country": "BR",
        "payment": "hotel",
        "accept": "on",
        **extra,
    }


def test_search_shows_availability_and_price_in_pen_or_usd_rf_web_01_02(setup, book, client):
    offers = services.search(setup.hotel, ARRIVAL, DEPARTURE, 2)
    double = next(o for o in offers if o.room_type == setup.double)
    assert double.available == 3
    rack = next(q for q in double.quotes if q.rate_plan == setup.rack)
    assert rack.total == Decimal("600.00")
    usd = services.search(setup.hotel, ARRIVAL, DEPARTURE, 2, currency="USD")[0].quotes[0]
    assert usd.currency == "USD" and usd.total < Decimal("200")
    resp = client.get(
        reverse("booking_engine:search"),
        {"llegada": ARRIVAL.isoformat(), "salida": DEPARTURE.isoformat(), "lang": "en"},
    )
    assert resp.status_code == 200
    assert b"Doble" in resp.content
    assert b"Check availability" in resp.content  # RF-WEB-02: inglés
    resp = client.get(reverse("booking_engine:search"), {"lang": "pt-br"})
    assert resp.context["lang"] == "pt-br"


def test_book_and_pay_at_hotel_with_extras_rf_web_03_04(setup, client):
    transfer = Service.objects.create(
        property=setup.hotel,
        kind="airport",
        name="Traslado aeropuerto",
        price=Decimal("120"),
        cost=Decimal("80"),
    )
    url = reverse("booking_engine:book") + "?" + "&".join(f"{k}={v}" for k, v in _params(setup).items())
    assert client.get(url).status_code == 200
    resp = client.post(url, {**_guest_data(), f"extra_{transfer.pk}": "2"})
    assert resp.status_code == 302
    r = Reservation.objects.get(guest__email="lucas@example.com")
    assert r.channel == "web" and r.status == "confirmed" and r.total_amount == Decimal("600.00")
    assert r.service_bookings.get().charge.amount == Decimal("240.00")
    assert resp["Location"] == reverse("booking_engine:confirmation", args=[r.portal_token])
    page = client.get(resp["Location"])
    assert reverse("portal:home", args=[r.portal_token]).encode() in page.content


def test_online_payment_guarantees_the_booking_rf_web_03(setup, client):
    url = reverse("booking_engine:book") + "?" + "&".join(f"{k}={v}" for k, v in _params(setup).items())
    resp = client.post(url, _guest_data(payment="online"))
    assert "/pagos/prueba/" in resp["Location"]
    r = Reservation.objects.get(guest__email="lucas@example.com")
    assert r.status == "pending"
    resp = client.post(resp["Location"], {"card": "4111 1111 1111 1111"})
    r.refresh_from_db()
    assert r.status == "guaranteed" and OnlinePayment.objects.get().status == "paid"
    assert resp["Location"].endswith(reverse("booking_engine:confirmation", args=[r.portal_token]))


def test_promo_code_and_honeypot_rf_web_04(setup, client):
    from django.utils import timezone

    from apps.rates.models import Promotion

    today = timezone.localdate()
    Promotion.objects.create(
        property=setup.hotel,
        code="VALLE10",
        name="Valle 10",
        discount_percent=Decimal("10"),
        valid_from=today - timedelta(days=5),
        valid_to=today + timedelta(days=30),
    )
    offers = services.search(setup.hotel, ARRIVAL, DEPARTURE, 2, promo_code="valle10")
    rack = next(q for q in offers[0].quotes if q.rate_plan == setup.rack)
    assert rack.discount_percent == Decimal("10") and rack.total == Decimal("540.00")
    url = reverse("booking_engine:book") + "?" + "&".join(f"{k}={v}" for k, v in _params(setup).items())
    client.post(url, _guest_data(website="http://spam.example"))
    assert not Reservation.objects.filter(guest__email="lucas@example.com").exists()


def test_group_request_notifies_sales_rf_web_05(setup, client, login):
    from apps.comms.models import Notification

    resp = client.post(
        reverse("booking_engine:group"),
        {
            "name": "Colegio Andino",
            "email": "viajes@colegio.example",
            "arrival": ARRIVAL.isoformat(),
            "departure": DEPARTURE.isoformat(),
            "rooms": 8,
            "pax": 20,
            "notes": "Promoción escolar",
        },
    )
    assert resp.status_code == 302
    assert GroupRequest.objects.get().rooms == 8
    assert Notification.objects.filter(role_code="sales").exists()
    assert login(setup.manager).get(reverse("booking_engine:group_list")).status_code == 200


def test_seo_robots_sitemap_and_jsonld_rf_web_06(setup, client):
    assert b"Sitemap:" in client.get("/robots.txt").content
    assert b"<urlset" in client.get("/sitemap.xml").content
    resp = client.get(reverse("booking_engine:search"))
    data = json.loads(resp.context["jsonld"])
    assert data["@type"] == "Hotel" and data["name"] == setup.hotel.name


@pytest.mark.parametrize("arrival_offset", [-1])
def test_cannot_search_past_dates(setup, arrival_offset):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        services.search(setup.hotel, BUSINESS_DATE + timedelta(days=arrival_offset), DEPARTURE)
