"""SUNAT simulada, anticipos, facturación agrupada y guías de remisión.

RF-FAC-01/03 (XML UBL, hash y CDR), RF-FAC-06 (facturación agrupada y anticipos), RF-FAC-09 (guía de
remisión), RF-FAC-10 (baja con ticket) y RNF-DIS-04. La SUNAT simulada no se configura: valida y
responde como la real.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.billing import services as billing
from apps.billing import ubl
from apps.billing.models import FakeTaxpayer, Invoice, RemissionLine, SunatRegistry, SunatTicket
from apps.billing.sunat import SimulatorAdapter
from apps.folio import services as folio

pytestmark = pytest.mark.django_db

VALID_RUC = "20100070970"
RUC_2 = "20131312955"


def _folio(setup, book, amount=Decimal("300"), **kw):
    r = book(**kw)
    f = r.main_folio
    folio.post_charge(f, folio.get_concept(setup.hotel, "lodging"), amount)
    return f


def _factura(setup, f, ruc=VALID_RUC, address="Av. El Sol 100, Cusco"):
    inv = billing.issue_invoice(
        f, "01", billing.Customer("6", ruc, "Andes Tours SAC", address), user=setup.receptionist, send=False
    )
    return billing.send_invoice(Invoice.objects.get(pk=inv.pk))


# -- XML, hash y constancia -------------------------------------------------


def test_xml_ubl_hash_and_cdr_rf_fac_03(setup, book, login):
    inv = _factura(setup, _folio(setup, book))
    assert inv.status == "accepted" and inv.sunat_code == "0"
    assert "<cbc:UBLVersionID>2.1</cbc:UBLVersionID>" in inv.xml
    assert 'listID="0101"' in inv.xml and "<cbc:ID>F001-00000001</cbc:ID>" in inv.xml
    assert ubl.declared_digest(inv.xml) == inv.hash == ubl.digest_of(inv.xml)
    assert "<cbc:ResponseCode>0</cbc:ResponseCode>" in inv.cdr_xml
    reg = SunatRegistry.objects.get(series="F001", number=1)
    assert reg.total == inv.total and reg.digest == inv.hash
    client = login(setup.receptionist)
    assert client.get(reverse("billing:invoice_file", args=[inv.pk, "xml"]))["Content-Type"].startswith(
        "application/xml"
    )
    cdr = client.get(reverse("billing:invoice_file", args=[inv.pk, "cdr"]))
    assert cdr["Content-Disposition"].endswith(f'R-{inv.file_name}.zip"')


def test_altered_xml_is_rejected(setup, book):
    f = _folio(setup, book)
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
    )
    inv.xml = inv.xml.replace("300.00", "30.00")
    inv.save(update_fields=["xml"])
    result = SimulatorAdapter().send(inv)
    assert not result.accepted and result.code == "2335"


def test_duplicate_number_with_other_data_is_rejected(setup, book):
    """Ej. se restauró un respaldo antiguo y el correlativo volvió a un número ya informado."""
    SunatRegistry.objects.create(
        issuer_ruc=setup.hotel.ruc,
        doc_type="03",
        series="B001",
        number=1,
        issue_date=setup.hotel.current_business_date(),
        total=Decimal("99"),
        digest="otro",
    )
    f = _folio(setup, book)
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
    )
    inv = billing.send_invoice(inv)
    assert inv.status == "rejected" and inv.sunat_code == "1033"
    # Reenviar el mismo XML aceptado devuelve la misma constancia (no se duplica)
    f2 = _folio(setup, book)
    ok = billing.send_invoice(
        billing.issue_invoice(
            f2, "03", billing.customer_from_folio(f2, "03"), user=setup.receptionist, send=False
        )
    )
    again = SimulatorAdapter().send(ok)
    assert ok.status == "accepted" and again.accepted and again.cdr == ok.cdr_xml


def test_factura_sent_after_three_days_is_rejected(setup, book):
    f = _folio(setup, book)
    inv = billing.issue_invoice(
        f,
        "01",
        billing.Customer("6", VALID_RUC, "Andes Tours SAC", "Cusco"),
        user=setup.receptionist,
        send=False,
    )
    setup.hotel.business_date = inv.issue_date + timedelta(days=4)
    setup.hotel.save()
    inv = billing.send_invoice(Invoice.objects.get(pk=inv.pk))
    assert inv.status == "rejected" and inv.sunat_code == "2108"


def test_no_habido_and_missing_address_are_observations(setup, book):
    FakeTaxpayer.objects.create(ruc=VALID_RUC, legal_name="ANDES TOURS SAC", condition="NO HABIDO")
    inv = _factura(setup, _folio(setup, book), address="")
    assert inv.status == "observed"
    assert {o.split(" - ")[0] for o in inv.observations} == {"4001", "4095"}
    assert SunatRegistry.objects.get(series="F001").status == "observed"


def test_export_of_services_requires_foreign_document(setup, book):
    r = book(guest=setup.foreigner)
    r.igv_exempt = True
    r.save()
    folio.post_charge(r.main_folio, folio.get_concept(setup.hotel, "lodging"), Decimal("300"))
    inv = billing.send_invoice(
        billing.issue_invoice(
            r.main_folio,
            "03",
            billing.Customer("1", "45678912", "John Smith"),
            user=setup.receptionist,
            send=False,
        )
    )
    assert inv.status == "rejected" and inv.sunat_code == "2642"
    ok = billing.send_invoice(
        billing.issue_invoice(
            r.main_folio,
            "03",
            billing.Customer("7", "X1234567", "John Smith"),
            user=setup.receptionist,
            send=False,
        )
    )
    assert ok.status == "accepted" and ok.export_amount == Decimal("300.00")


# -- Baja con ticket (RF-FAC-10) ---------------------------------------------


def test_factura_void_goes_through_ra_ticket(setup, book, settings):
    settings.SUNAT_TICKET_SECONDS = 60
    inv = _factura(setup, _folio(setup, book))
    billing.void_invoice(inv, "Datos del cliente errados", user=setup.auditor)
    ticket = SunatTicket.objects.get()
    assert ticket.kind == "RA" and len(ticket.number) <= 15 and "<VoidedDocuments" in ticket.xml
    assert billing.check_ticket(ticket.number).processing  # SUNAT aún procesa
    inv.refresh_from_db()
    assert inv.status == "voiding"
    SunatTicket.objects.filter(pk=ticket.pk).update(ready_at=timezone.now())
    assert billing.poll_tickets(setup.hotel) == 1
    inv.refresh_from_db()
    assert inv.status == "voided" and SunatRegistry.objects.get(series="F001").status == "voided"
    assert inv.folio.uninvoiced_charges.count() == 1


def test_daily_summary_informs_boletas_left_pending(setup, book, monkeypatch):
    from apps.billing.tests.test_billing import _offline

    f = _folio(setup, book)
    with monkeypatch.context() as m:
        _offline(m)
        inv = billing.send_invoice(
            billing.issue_invoice(
                f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
            )
        )
    assert inv.status == "pending"
    sub = billing.daily_summary(setup.hotel, inv.issue_date)
    assert sub.ticket and SunatTicket.objects.get(number=sub.ticket).kind == "RC"
    inv.refresh_from_db()
    assert inv.status == "accepted"
    assert SunatRegistry.objects.filter(series="B001", number=inv.number).exists()


def test_credit_note_requires_informed_document(setup, book):
    inv = _factura(setup, _folio(setup, book))
    SunatRegistry.objects.filter(series="F001").update(status="voided")  # SUNAT ya no lo tiene vigente
    note = billing.send_invoice(billing.credit_note(inv, "01", "Anulación", user=setup.auditor))
    note.refresh_from_db()
    assert note.status == "rejected" and note.sunat_code == "2524"


# -- RF-FAC-06: anticipos y facturación agrupada --------------------------


def test_advance_invoice_is_deducted_from_final_invoice_rf_fac_06(setup, book):
    r = book()
    f = r.main_folio
    folio.add_payment(f, "transfer", Decimal("236"), user=setup.receptionist, is_deposit=True)
    assert billing.deposits_available(f) == Decimal("236.00")
    customer = billing.customer_from_folio(f, "03")
    with pytest.raises(ValidationError):
        billing.issue_advance(f, "03", customer, Decimal("500"), user=setup.receptionist)
    adv = billing.send_invoice(
        billing.issue_advance(f, "03", customer, Decimal("236"), user=setup.receptionist, send=False)
    )
    assert adv.status == "accepted" and adv.is_advance and adv.igv == Decimal("36.00")
    assert billing.deposits_available(f) == 0
    folio.post_charge(f, folio.get_concept(setup.hotel, "lodging"), Decimal("590"))
    final = billing.send_invoice(
        billing.issue_invoice(f, "03", customer, user=setup.receptionist, send=False)
    )
    assert final.status == "accepted"
    assert final.prepaid_amount == Decimal("236.00") and final.total == Decimal("354.00")
    assert final.taxed_amount == Decimal("300.00") and final.igv == Decimal("54.00")
    assert "<cac:PrepaidPayment>" in final.xml and adv.full_number in final.xml
    adv.refresh_from_db()
    assert adv.applied_to == final


def test_grouped_invoice_for_agency_rf_fac_06(setup, book, login):
    from apps.guests.models import Company

    agency = Company.objects.create(
        ruc=VALID_RUC,
        legal_name="Valle Sagrado Travel EIRL",
        kind="agency",
        credit_days=30,
        address="Av. Pardo 200, Cusco",
    )
    f1 = _folio(setup, book, company=agency)
    f2 = _folio(setup, book, Decimal("200"), company=agency, room=setup.rooms[1])
    today = setup.hotel.current_business_date()
    charges = list(billing.grouped_charges(setup.hotel, agency, today, today + timedelta(days=1)))
    assert len(charges) == 2
    inv = billing.send_invoice(
        billing.issue_grouped_invoice(setup.hotel, agency, charges, user=setup.receptionist, send=False)
    )
    assert inv.status == "accepted" and inv.folio is None and inv.total == Decimal("500.00")
    assert inv.due_date == today + timedelta(days=30) and not inv.is_paid
    assert (
        inv.lines.count() == 2
        and f1.reservation.code in inv.lines.first().description + inv.lines.last().description
    )
    assert f1.uninvoiced_charges.count() == 0 and f2.uninvoiced_charges.count() == 0
    resp = login(setup.receptionist).get(
        reverse("billing:grouped"),
        {"company": agency.pk, "start": today.isoformat(), "end": today.isoformat()},
    )
    assert resp.status_code == 200


# -- RF-FAC-09: guía de remisión ----------------------------------------------


def _guide(setup, **kw):
    data = {
        "reason": "13",
        "reason_detail": "Lavandería externa",
        "recipient_doc_type": "6",
        "recipient_doc": RUC_2,
        "recipient_name": "Lavandería Urubamba SAC",
        "destination_address": "Jr. Grau 300, Urubamba",
        "destination_ubigeo": "081301",
        "gross_weight": Decimal("25"),
        "packages": 3,
        "transport_mode": "02",
        "vehicle_plate": "ABC-123",
        "driver_doc": "40000002",
        "driver_name": "Julio Mamani",
        "driver_license": "Q40000002",
    }
    data.update(kw)
    g = billing.new_guide(setup.hotel, **data)
    g.origin_ubigeo = "081301"
    g.origin_address = "Av. Mariscal Castilla 100, Urubamba"
    g.save()
    RemissionLine.objects.create(guide=g, description="Sábanas de 2 plazas", unit="NIU", quantity=40)
    return g


def test_remission_guide_accepted_through_ticket_rf_fac_09(setup, login):
    g = billing.issue_guide(_guide(setup), user=setup.receptionist)
    assert g.full_number == "T001-00000001" and g.status == "processing"
    assert "<DespatchAdvice" in g.xml and "<cbc:HandlingCode>13</cbc:HandlingCode>" in g.xml
    billing.check_ticket(g.ticket.number)
    g.refresh_from_db()
    assert g.status == "accepted" and g.cdr_xml
    assert SunatRegistry.objects.filter(doc_type="09", series="T001", number=1).exists()
    client = login(setup.receptionist)
    assert client.get(reverse("billing:guide_file", args=[g.pk, "pdf"])).content[:4] == b"%PDF"
    assert client.get(reverse("billing:guide_detail", args=[g.pk])).status_code == 200


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"vehicle_plate": "123"}, "3302"),
        ({"transport_mode": "01", "carrier_ruc": "123", "carrier_name": ""}, "3301"),
        ({"reason": "04"}, "3306"),
        ({"destination_ubigeo": "81301"}, "3305"),
    ],
)
def test_remission_guide_validations(setup, changes, code):
    g = billing.issue_guide(_guide(setup, **changes), user=setup.receptionist)
    billing.check_ticket(g.ticket.number)
    g.refresh_from_db()
    assert g.status == "rejected" and g.sunat_code == code


def test_guide_form_creates_and_sends(setup, login):
    client = login(setup.receptionist)
    data = {
        "reason": "06",
        "transfer_date": setup.hotel.current_business_date().isoformat(),
        "recipient_doc_type": "6",
        "recipient_doc": RUC_2,
        "recipient_name": "Proveedor SAC",
        "origin_address": "Urubamba",
        "origin_ubigeo": "081301",
        "destination_address": "Cusco",
        "destination_ubigeo": "080101",
        "gross_weight": "10",
        "packages": "1",
        "transport_mode": "01",
        "carrier_ruc": VALID_RUC,
        "carrier_name": "Transportes Inka SAC",
        "l-TOTAL_FORMS": "1",
        "l-INITIAL_FORMS": "0",
        "l-MIN_NUM_FORMS": "0",
        "l-MAX_NUM_FORMS": "1000",
        "l-0-description": "Licuadora industrial (devolución)",
        "l-0-unit": "NIU",
        "l-0-quantity": "1",
        "send": "1",
    }
    resp = client.post(reverse("billing:guide_create"), data)
    assert resp.status_code == 302
    from apps.billing.models import RemissionGuide

    g = RemissionGuide.objects.get()
    assert g.status in ("processing", "accepted") and g.lines.count() == 1


# -- Consulta pública de validez ---------------------------------------------


def test_public_validity_check(setup, book, client):
    inv = _factura(setup, _folio(setup, book))
    url = reverse("cpe_validity")
    ok = client.get(
        url, {"ruc": setup.hotel.ruc, "tipo": "01", "serie": "F001", "numero": "1", "total": str(inv.total)}
    )
    assert ok.context["result"]["ok"]
    bad = client.get(
        url, {"ruc": setup.hotel.ruc, "tipo": "01", "serie": "F001", "numero": "1", "total": "1"}
    )
    assert not bad.context["result"]["ok"]
    missing = client.get(url, {"ruc": setup.hotel.ruc, "tipo": "01", "serie": "F001", "numero": "99"})
    assert "no ha sido informado" in missing.context["result"]["text"]


def test_sunat_panel_has_no_configuration(setup, login):
    resp = login(setup.manager).get(reverse("billing:sunat"))
    assert resp.status_code == 200
    assert b"reject_next" not in resp.content and b"<select" not in resp.content
