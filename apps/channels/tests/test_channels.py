"""Channel manager: RF-CHA-01 a RF-CHA-04."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.channels import services
from apps.channels.models import Channel, ChannelInventory, RateMapping, RoomMapping, SyncLog
from apps.reservations.models import Reservation
from conftest import BUSINESS_DATE


@pytest.fixture
def channel(setup):
    ch = Channel.objects.create(
        property=setup.hotel, code="booking", name="Booking.com", commission_percent=Decimal("15")
    )
    RoomMapping.objects.create(channel=ch, room_type=setup.double, external_code="BKG-DBL")
    RoomMapping.objects.create(channel=ch, room_type=setup.suite, external_code="BKG-STE")
    RateMapping.objects.create(
        channel=ch, rate_plan=setup.rack, external_code="BAR", markup_percent=Decimal("10")
    )
    return ch


def _payload(**extra):
    arrival = BUSINESS_DATE + timedelta(days=5)
    return {
        "external_id": "BKG-1001",
        "room_code": "BKG-DBL",
        "rate_code": "BAR",
        "arrival": arrival.isoformat(),
        "departure": (arrival + timedelta(days=2)).isoformat(),
        "adults": 2,
        "total": "700",
        "guest": {
            "first_name": "Ana",
            "last_name": "Lima",
            "email": "ana.lima@example.com",
            "country": "BR",
            "language": "pt-br",
        },
        **extra,
    }


def test_push_publishes_availability_and_marked_up_price_rf_cha_01(setup, channel):
    log = services.push_channel(channel, days=3)
    assert log.status == SyncLog.Status.OK
    inv = ChannelInventory.objects.get(channel=channel, room_type=setup.double, date=BUSINESS_DATE)
    assert inv.available == 3
    assert inv.price == Decimal("330.00")  # 300 rack + 10 % del canal
    channel.refresh_from_db()
    assert channel.last_sync_at is not None


def test_inbound_reservation_lowers_availability_everywhere_rf_cha_02(setup, channel, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    r = services.receive_reservation(channel, _payload())
    assert r.channel == "booking" and r.external_ref == "BKG-1001"
    assert r.total_amount == Decimal("700.00")  # tarifa que cobró el canal
    assert services.is_dirty(setup.hotel)
    services.push_all(setup.hotel)
    inv = ChannelInventory.objects.get(channel=channel, room_type=setup.double, date=r.arrival)
    assert inv.available == 2
    # duplicada: no crea otra
    assert services.receive_reservation(channel, _payload()).pk == r.pk
    assert Reservation.objects.filter(external_ref="BKG-1001").count() == 1
    # cancelación del canal
    services.receive_reservation(channel, _payload(status="cancelled"))
    r.refresh_from_db()
    assert r.status == "cancelled"


def test_commission_by_channel_rf_cha_03(setup, channel):
    services.receive_reservation(channel, _payload())
    rows = services.commission_report(setup.hotel, BUSINESS_DATE, BUSINESS_DATE + timedelta(days=30))
    assert rows[0]["revenue"] == Decimal("700.00") and rows[0]["commission"] == Decimal("105.00")


def test_errors_panel_retry_and_manager_alert_rf_cha_04(setup, channel, login):
    from apps.comms.models import Notification

    channel.is_active = False
    channel.save()
    log = services.push_channel(channel, days=2)
    assert log.status == SyncLog.Status.ERROR
    assert Notification.objects.filter(role_code="manager", property=setup.hotel).exists()
    unknown = services.receive_reservation(channel, _payload(room_code="NO-EXISTE", external_id="X"))
    assert unknown is None and SyncLog.objects.filter(direction="pull", status="error").exists()
    channel.is_active = True
    channel.save()
    assert services.retry(log).status == SyncLog.Status.OK
    resp = login(setup.manager).get(reverse("channels:panel"))
    assert resp.status_code == 200
