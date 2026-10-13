"""Portal del huésped, pagos en línea y reclamos: RF-POR-01/02/03, RF-REC-05, RF-WEB-03, RF-HUE-05, RF-COMU-03."""

import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.folio import services as folio
from apps.payments.gateways import TestGateway
from apps.payments.models import OnlinePayment
from apps.payments.services import complete, create_payment
from apps.portal.models import Complaint, ServiceRequest, Survey

pytestmark = pytest.mark.django_db


def test_portal_home_in_guest_language(setup, book, client):
    r = book(guest=setup.foreigner)
    resp = client.get(reverse("portal:home", args=[r.portal_token]) + "?lang=en")
    assert resp.status_code == 200
    assert b"Online pre-check-in" in resp.content
    resp = client.get(reverse("portal:home", args=[r.portal_token]) + "?lang=pt-br")
    assert "Pré-check-in on-line".encode() in resp.content


def test_unknown_or_cancelled_token_is_404(setup, book, client):
    import uuid

    assert client.get(reverse("portal:home", args=[uuid.uuid4()])).status_code == 404
    r = book()
    r.status = "cancelled"
    r.save()
    assert client.get(reverse("portal:home", args=[r.portal_token])).status_code == 404


def test_online_precheckin_rf_rec_05(setup, book, client):
    r = book(guest=setup.foreigner)
    resp = client.post(
        reverse("portal:precheckin", args=[r.portal_token]),
        {
            "first_name": "John",
            "last_name": "Smith",
            "doc_type": "7",
            "doc_number": "X9999999",
            "nationality": "us",
            "email": "john@example.com",
            "phone": "+1 202 555 0101",
            "eta": "15:30",
            "signature": "data:image/png;base64,AA",
            "consent": "on",
        },
    )
    assert resp.status_code == 302
    r.refresh_from_db()
    assert r.precheckin_at is not None and r.eta.hour == 15
    assert r.registration_card.signature.startswith("data:image")
    r.guest.refresh_from_db()
    assert r.guest.doc_number == "X9999999" and r.guest.data_consent_at is not None


def test_service_request_notifies_staff_rf_por_02(setup, book, client):
    from apps.comms.models import Notification

    r = book()
    client.post(
        reverse("portal:request", args=[r.portal_token]), {"kind": "oxygen", "notes": "Me falta el aire"}
    )
    assert ServiceRequest.objects.get(reservation=r).kind == "oxygen"
    assert Notification.objects.filter(role_code="receptionist").exists()


def test_online_payment_flow_rf_web_03(setup, book, client):
    r = book()
    p = create_payment(setup.hotel, Decimal("300"), "Depósito", reservation=r, return_url="/")
    assert TestGateway().charge("4000 0000 0000 0002").ok is False
    complete(p, TestGateway().charge("4111111111111111"))
    p.refresh_from_db()
    assert p.status == "paid" and p.card_last4 == "1111"
    assert r.main_folio.total_payments == Decimal("300.00")
    assert not hasattr(p, "card_number")  # nunca se guarda la tarjeta
    complete(p, TestGateway().charge("4111111111111111"))  # idempotente
    assert r.main_folio.payments.count() == 1


def test_portal_pay_redirects_to_gateway(setup, book, client):
    r = book()
    resp = client.post(reverse("portal:pay", args=[r.portal_token]))
    assert resp.status_code == 302 and "/pagos/prueba/" in resp["Location"]
    payment = OnlinePayment.objects.get()
    resp = client.post(resp["Location"], {"card": "4111 1111 1111 1111"})
    payment.refresh_from_db()
    assert payment.status == "paid"


def test_folio_and_invoice_download_rf_por_03(setup, book, client):
    from apps.billing import services as billing

    r = book()
    folio.post_charge(r.main_folio, folio.get_concept(setup.hotel, "laundry"), Decimal("20"))
    inv = billing.issue_invoice(
        r.main_folio,
        "03",
        billing.customer_from_folio(r.main_folio, "03"),
        user=setup.receptionist,
        send=False,
    )
    assert client.get(reverse("portal:folio", args=[r.portal_token])).status_code == 200
    resp = client.get(reverse("portal:invoice_pdf", args=[r.portal_token, inv.pk]))
    assert resp["Content-Type"] == "application/pdf"


def test_survey_once_and_alerts_on_low_score_rf_hue_05(setup, book, client):
    from apps.comms.models import Notification

    r = book()
    data = {"overall": 2, "room": 3, "cleanliness": 2, "service": 2, "comments": "Ruido"}
    client.post(reverse("portal:survey", args=[r.portal_token]), data)
    assert Survey.objects.get(reservation=r).average == 2.2
    assert Notification.objects.filter(role_code="manager", level="warning").exists()
    client.post(reverse("portal:survey", args=[r.portal_token]), {**data, "overall": 5})
    assert Survey.objects.count() == 1


def test_complaint_book_registers_and_answers(setup, client, login):
    resp = client.post(
        reverse("portal:complaint_book", args=[setup.hotel.code]),
        {
            "kind": "reclamo",
            "full_name": "Ana Pérez",
            "doc_number": "40000001",
            "email": "ana@example.com",
            "description": "No funcionó el agua caliente",
            "request": "Descuento",
        },
    )
    assert resp.status_code == 200
    c = Complaint.objects.get()
    assert c.number.endswith("00001")
    staff = login(setup.manager)
    staff.post(
        reverse("portal:staff_complaint", args=[c.pk]), {"response": "Le ofrecemos 20%", "status": "answered"}
    )
    c.refresh_from_db()
    assert c.responded_at is not None


def test_whatsapp_inbound_message_rf_comu_03(setup, book, client, settings):
    from apps.comms.models import Message

    setup.foreigner.phone = "+12025550101"
    setup.foreigner.save()
    book(guest=setup.foreigner)
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"from": "12025550101", "text": {"body": "Hi!"}}]}}]}]
    }
    resp = client.post(
        reverse("comms:whatsapp_webhook"), json.dumps(payload), content_type="application/json"
    )
    assert resp.status_code == 200
    assert Message.objects.get(direction="in").body == "Hi!"
    settings.WHATSAPP_VERIFY_TOKEN = "abc"
    assert (
        client.get(
            reverse("comms:whatsapp_webhook"), {"hub.verify_token": "abc", "hub.challenge": "42"}
        ).content
        == b"42"
    )


def test_scheduler_runs_idempotently(setup, book):
    from apps.comms.models import MessageTemplate
    from apps.core.scheduler import run_all

    MessageTemplate.objects.create(
        property=setup.hotel, event="reminder", language="es", subject="Pronto", body="Hola"
    )
    book(arrival_offset=2)
    first = run_all(setup.hotel)
    assert first["recordatorios_48h"] == 1
    assert run_all(setup.hotel)["recordatorios_48h"] == 0
