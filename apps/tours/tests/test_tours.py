"""Tours y traslados: RF-TUR-01 a RF-TUR-05."""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.comms.models import Message
from apps.tours import services
from apps.tours.models import Operator, Service, ServiceBooking
from conftest import BUSINESS_DATE


@pytest.fixture
def catalog(setup):
    op = Operator.objects.create(property=setup.hotel, name="Inka Tours", email="ops@inka.example")
    valle = Service.objects.create(
        property=setup.hotel,
        kind="sacred_valley",
        name="Valle Sagrado",
        operator=op,
        price=Decimal("180"),
        cost=Decimal("120"),
        pickup_time=time(8, 30),
    )
    airport = Service.objects.create(
        property=setup.hotel,
        kind="airport",
        name="Traslado aeropuerto",
        operator=op,
        price=Decimal("120"),
        cost=Decimal("80"),
    )
    return op, valle, airport


def test_sale_posts_to_folio_with_price_and_cost_rf_tur_01_02(setup, book, catalog):
    _op, valle, airport = catalog
    r = book()
    sb = services.book_service(valle, date=BUSINESS_DATE + timedelta(days=1), pax=2, reservation=r)
    assert sb.guest_name == "María Quispe" and sb.pickup_time == time(8, 30)
    assert sb.charge.amount == Decimal("360.00") and sb.charge.concept.code == "tour"
    assert sb.total_cost == Decimal("240")
    transfer = services.book_service(airport, date=BUSINESS_DATE, reservation=r)
    assert transfer.charge.concept.code == "transfer"
    # cancelar anula el cargo
    services.cancel_service(sb, setup.auditor)
    sb.charge.refresh_from_db()
    assert sb.status == "cancelled" and sb.charge.is_void


def test_daily_agenda_sent_to_operator_rf_tur_03(setup, book, catalog):
    op, valle, _airport = catalog
    day = BUSINESS_DATE + timedelta(days=1)
    services.book_service(valle, date=day, pax=2, reservation=book(), notes="Vegetariano")
    services.book_service(valle, date=day, pax=1, guest_name="Pasajero externo")
    assert services.agenda(setup.hotel, day).count() == 2
    assert services.send_agenda(setup.hotel, day, op) == 2
    msg = Message.objects.get(to="ops@inka.example")
    assert "Vegetariano" in msg.body and "08:30" in msg.body
    assert set(ServiceBooking.objects.values_list("status", flat=True)) == {"confirmed"}


def test_train_alert_for_early_breakfast_rf_tur_04(setup, book):
    from apps.frontdesk import services as fd

    r = book(room=setup.rooms[0])
    fd.check_in(r, user=setup.receptionist, charge_early=False, allow_dirty=True)
    r.train_date = BUSINESS_DATE + timedelta(days=1)
    r.train_time = time(6, 10)
    r.save()
    assert list(services.train_alerts(setup.hotel, BUSINESS_DATE)) == [r]


def test_settlement_by_operator_rf_tur_05(setup, book, catalog, login):
    _op, valle, airport = catalog
    services.book_service(valle, date=BUSINESS_DATE, pax=2, reservation=book())
    services.book_service(airport, date=BUSINESS_DATE, pax=1, guest_name="Externo")
    row = services.settlement(setup.hotel, BUSINESS_DATE, BUSINESS_DATE + timedelta(days=1))[0]
    assert (
        row["sales"] == Decimal("480") and row["cost"] == Decimal("320") and row["margin"] == Decimal("160")
    )
    client = login(setup.receptionist)
    assert client.get(reverse("tours:agenda")).status_code == 200
    assert client.get(reverse("tours:settlement")).status_code == 200
    resp = client.post(
        reverse("tours:sell"),
        {
            "service": valle.pk,
            "guest_name": "Walk-up",
            "pax": 1,
            "date": BUSINESS_DATE.isoformat(),
            "pickup_point": "Lobby",
        },
    )
    assert resp.status_code == 302 and ServiceBooking.objects.filter(guest_name="Walk-up").exists()
