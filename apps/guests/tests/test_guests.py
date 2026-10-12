"""Huéspedes y comunicaciones: RF-HUE-01/02/06, RNF-SEG-04, RF-RES-11."""

import pytest
from django.core import mail
from django.db import connection

from apps.comms.models import MessageTemplate
from apps.comms.services import send_event
from apps.guests.models import Guest
from apps.guests.services import anonymize, find_duplicates, merge_guests

pytestmark = pytest.mark.django_db


def test_document_and_health_data_encrypted_at_rest_rnf_seg_04(db):
    g = Guest.objects.create(first_name="Ana", last_name="Tito", doc_number="AB998877", allergies="Maní")
    with connection.cursor() as cur:
        cur.execute("SELECT doc_number, allergies FROM guests_guest WHERE id = %s", [g.pk])
        raw_doc, raw_allergies = cur.fetchone()
    assert "AB998877" not in raw_doc and raw_doc.startswith("enc$")
    assert "Maní" not in raw_allergies
    assert Guest.objects.get(pk=g.pk).doc_number == "AB998877"


def test_duplicates_by_document_email_or_phone_rf_hue_02(db):
    a = Guest.objects.create(
        first_name="Ana", last_name="Tito", doc_number="ab-998877", email="ana@x.com", phone="+51 984 111 222"
    )
    assert list(find_duplicates(doc_number="AB998877")) == [a]
    assert list(find_duplicates(email="ANA@x.com")) == [a]
    assert list(find_duplicates(phone="984111222")) == [a]


def test_merge_moves_reservations(setup, book):
    dup = Guest.objects.create(first_name="Maria", last_name="Quispe", email="otro@x.com", phone="999")
    r = book(guest=dup)
    merge_guests(setup.peruvian, dup)
    r.refresh_from_db()
    assert r.guest == setup.peruvian
    assert not Guest.objects.filter(pk=dup.pk).exists()


def test_anonymize_keeps_record_without_personal_data_rf_hue_06(db):
    g = Guest.objects.create(first_name="Ana", last_name="Tito", doc_number="X1", email="a@x.com")
    anonymize(g, "Solicitud del titular")
    g.refresh_from_db()
    assert (g.first_name, g.doc_number, g.email) == ("Anonimizado", "", "")


def test_non_domiciled_rules(setup):
    assert setup.foreigner.is_non_domiciled
    assert not setup.peruvian.is_non_domiciled


def test_confirmation_email_in_guest_language_with_pdf_rf_res_11(setup, book):
    for lang, subject in (
        ("es", "Reserva {{ reservation.code }} confirmada"),
        ("en", "Booking {{ reservation.code }} confirmed"),
    ):
        MessageTemplate.objects.create(
            property=setup.hotel,
            event="confirmation",
            language=lang,
            subject=subject,
            body="Hola {{ guest.first_name }}",
        )
    r = book(guest=setup.foreigner)
    send_event("confirmation", r)
    assert mail.outbox[-1].subject == f"Booking {r.code} confirmed"
    assert mail.outbox[-1].attachments[0][0] == f"reserva-{r.code}.pdf"
    r2 = book()
    send_event("confirmation", r2)
    assert mail.outbox[-1].subject.startswith("Reserva")
