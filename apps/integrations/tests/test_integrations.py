"""Integraciones opcionales de la fase 4: cerraduras de tarjeta y central telefónica (PBX)."""

import json
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.frontdesk import services as fd
from apps.integrations import services
from apps.integrations.adapters import classify
from apps.integrations.models import CallRecord, KeyCard


@pytest.fixture
def in_house(setup, book):
    r = book(room=setup.rooms[0])
    fd.check_in(r, user=setup.receptionist, charge_early=False, allow_dirty=True)
    return r


def test_check_in_encodes_and_check_out_revokes_keys(setup, in_house):
    cards = KeyCard.objects.filter(reservation=in_house)
    assert cards.count() == 2 and all(c.status == "active" for c in cards)
    assert cards.first().card_ref.startswith("T101-")
    fd.move_room(in_house, setup.rooms[1], kind="upgrade", reason="Ruido", user=setup.receptionist)
    assert KeyCard.objects.filter(reservation=in_house, status="active", room=setup.rooms[1]).count() == 2
    assert KeyCard.objects.filter(reservation=in_house, status="revoked", room=setup.rooms[0]).count() == 2


def test_lock_failure_does_not_block_check_in(setup, book, monkeypatch):
    from apps.comms.models import Notification
    from apps.integrations import adapters

    def broken(self, *a, **k):
        raise ConnectionError("codificador desconectado")

    monkeypatch.setattr(adapters.TestLock, "encode", broken)
    r = book(room=setup.rooms[2])
    fd.check_in(r, user=setup.receptionist, charge_early=False, allow_dirty=True)
    assert r.status == "checked_in"
    assert Notification.objects.filter(role_code="receptionist", title__icontains="codificador").exists()


@pytest.mark.parametrize(
    "number,kind",
    [
        ("105", "internal"),
        ("084201234", "national"),
        ("987654321", "mobile"),
        ("+51987654321", "mobile"),
        ("+12025550101", "international"),
        ("2012345", "local"),
    ],
)
def test_classify_peruvian_numbers(number, kind):
    assert classify(number) == kind


def test_call_is_charged_to_the_guest_once(setup, in_house):
    payload = {
        "uniqueid": "1700.1",
        "src": "101",
        "dst": "+12025550101",
        "start": timezone.now().isoformat(),
        "billsec": 125,
    }
    rec = services.register_call(setup.hotel, payload)
    assert rec.kind == "international" and rec.cost == Decimal("15.00")  # 3 minutos × S/ 5
    assert rec.charge.amount == Decimal("15.00") and rec.charge.folio.reservation == in_house
    assert "***" in rec.charge.description  # número parcialmente oculto en el folio
    assert services.register_call(setup.hotel, payload).pk == rec.pk  # reenvío de la central
    assert CallRecord.objects.count() == 1


def test_pbx_webhook_requires_token(setup, in_house, client, settings):
    settings.PBX_TOKEN = "secreto-de-prueba"
    url = reverse("integrations:pbx_webhook")
    body = json.dumps(
        {
            "uniqueid": "9",
            "src": "101",
            "dst": "987654321",
            "start": timezone.now().isoformat(),
            "billsec": 30,
        }
    )
    assert client.post(url, body, content_type="application/json").status_code == 403
    resp = client.post(url, body, content_type="application/json", HTTP_X_PBX_TOKEN="secreto-de-prueba")
    assert resp.json() == {"ok": True, "registered": 1}
    assert CallRecord.objects.get().cost == Decimal("1.00")


def test_panel_duplicate_key_and_simulated_call(setup, in_house, login):
    client = login(setup.receptionist)
    assert client.get(reverse("integrations:panel")).status_code == 200
    client.post(reverse("integrations:duplicate_key", args=[in_house.pk]))
    assert KeyCard.objects.filter(reservation=in_house, status="active").count() == 3
    client.post(reverse("integrations:duplicate_key", args=[in_house.pk]), {"lost": "1"})
    assert KeyCard.objects.filter(reservation=in_house, status="active").count() == 2
    client.post(
        reverse("integrations:simulate_call"), {"extension": "101", "dialed": "987654321", "seconds": 61}
    )
    assert CallRecord.objects.get().cost == Decimal("2.00")
    assert client.get(reverse("reservations:reservation_detail", args=[in_house.pk])).status_code == 200
