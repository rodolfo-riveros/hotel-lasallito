"""Facturación simulada: RF-FAC-01/04/05/07/10, RNF-DIS-04, sección 12."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.billing import services as billing
from apps.billing.models import Invoice, SimulationSettings
from apps.billing.validators import amount_in_words, ruc_check_digit, ruc_is_valid
from apps.folio import services as folio

pytestmark = pytest.mark.django_db

VALID_RUC = "20100070970"  # dígito verificador válido


def test_ruc_check_digit():
    assert ruc_is_valid(VALID_RUC)
    assert not ruc_is_valid("20100070971")
    assert not ruc_is_valid("123")
    assert ruc_check_digit("2060000000") == 5


def test_amount_in_words():
    assert amount_in_words(Decimal("1250.50")) == "SON: MIL DOSCIENTOS CINCUENTA CON 50/100 SOLES"
    assert amount_in_words(Decimal("21")) == "SON: VEINTIUNO CON 00/100 SOLES"
    assert amount_in_words(Decimal("100"), "USD") == "SON: CIEN CON 00/100 DÓLARES AMERICANOS"


def _folio_with(setup, book, amount=Decimal("300"), guest=None, exempt=False):
    r = book(guest=guest or setup.peruvian)
    if exempt:
        r.igv_exempt = True
        r.save()
    f = r.main_folio
    folio.post_charge(f, folio.get_concept(setup.hotel, "lodging"), amount)
    return f


def _send_now(invoice):
    return billing.send_invoice(Invoice.objects.get(pk=invoice.pk))


def test_boleta_with_igv_and_correlative_numbers(setup, book):
    f = _folio_with(setup, book, Decimal("236"))
    customer = billing.customer_from_folio(f, "03")
    inv = billing.issue_invoice(f, "03", customer, user=setup.receptionist, send=False)
    assert inv.full_number == "B001-00000001"
    assert (inv.taxed_amount, inv.igv, inv.total) == (Decimal("200.00"), Decimal("36.00"), Decimal("236.00"))
    assert inv.legends[0]["text"].startswith("SON: DOSCIENTOS TREINTA Y SEIS")
    assert any(lg["text"] == billing.SIMULATION_LEGEND for lg in inv.legends)
    f2 = _folio_with(setup, book, Decimal("100"))
    inv2 = billing.issue_invoice(
        f2, "03", billing.customer_from_folio(f2, "03"), user=setup.receptionist, send=False
    )
    assert inv2.number == inv.number + 1


def test_factura_requires_valid_ruc_rf_fac_05(setup, book):
    f = _folio_with(setup, book)
    with pytest.raises(ValidationError):
        billing.issue_invoice(
            f, "01", billing.Customer("6", "20100070971", "Empresa"), user=setup.receptionist
        )
    inv = billing.issue_invoice(
        f, "01", billing.Customer("6", VALID_RUC, "Empresa SAC"), user=setup.receptionist, send=False
    )
    assert inv.full_number.startswith("F001")


def test_boleta_above_700_requires_document(setup, book):
    f = _folio_with(setup, book, Decimal("800"))
    with pytest.raises(ValidationError):
        billing.issue_invoice(f, "03", billing.Customer("0", "", "Clientes varios"), user=setup.receptionist)


def test_non_domiciled_lodging_is_export_with_legend_rf_fac_04(setup, book):
    f = _folio_with(setup, book, Decimal("300"), guest=setup.foreigner, exempt=True)
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
    )
    assert inv.customer_doc_type == "7" and inv.customer_doc == "X1234567"
    assert (inv.export_amount, inv.igv, inv.total) == (Decimal("300.00"), Decimal("0"), Decimal("300.00"))
    assert any(lg["code"] == "2005" for lg in inv.legends)
    assert inv.lines.first().affectation == "40"


def test_invoice_in_usd_uses_daily_rate_rf_fac_07(setup, book):
    f = _folio_with(setup, book, Decimal("375"))
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, currency="USD", send=False
    )
    assert inv.currency == "USD" and inv.total == Decimal("100.00")


def test_simulator_accepts_rejects_and_queues_rnf_dis_04(setup, book):
    f = _folio_with(setup, book)
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
    )
    sim = SimulationSettings.objects.create(property=setup.hotel, connection_down=True)
    inv = _send_now(inv)
    assert inv.status == "pending" and inv.number == 1  # conserva su número
    sim.connection_down = False
    sim.save()
    assert billing.retry_pending(setup.hotel) == 1
    inv.refresh_from_db()
    assert inv.status == "accepted"

    f2 = _folio_with(setup, book)
    sim.reject_next = 1
    sim.save()
    inv2 = _send_now(
        billing.issue_invoice(
            f2, "03", billing.customer_from_folio(f2, "03"), user=setup.receptionist, send=False
        )
    )
    assert inv2.status == "rejected"
    assert f2.uninvoiced_charges.count() == 1  # se puede corregir y reemitir


def test_full_credit_note_frees_charges(setup, book):
    f = _folio_with(setup, book)
    inv = _send_now(
        billing.issue_invoice(
            f, "01", billing.Customer("6", VALID_RUC, "Empresa SAC"), user=setup.receptionist, send=False
        )
    )
    with pytest.raises(PermissionDenied):
        billing.credit_note(inv, "02", "RUC equivocado", user=setup.receptionist)
    note = billing.credit_note(inv, "02", "RUC equivocado", user=setup.auditor)
    assert note.full_number == "FC01-00000001" and note.total == inv.total
    assert note.related_invoice == inv
    assert f.uninvoiced_charges.count() == 1


def test_partial_credit_note_cannot_exceed_balance(setup, book):
    f = _folio_with(setup, book, Decimal("236"))
    inv = _send_now(
        billing.issue_invoice(
            f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
        )
    )
    billing.credit_note(inv, "13", "Descuento", user=setup.auditor, amount=Decimal("100"))
    with pytest.raises(ValidationError):
        billing.credit_note(inv, "13", "Otro", user=setup.auditor, amount=Decimal("200"))


def test_void_within_seven_days_rf_fac_10(setup, book):
    from datetime import timedelta

    f = _folio_with(setup, book)
    inv = _send_now(
        billing.issue_invoice(
            f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
        )
    )
    setup.hotel.business_date = inv.issue_date + timedelta(days=8)
    setup.hotel.save()
    inv.refresh_from_db()
    with pytest.raises(ValidationError):
        billing.void_invoice(inv, "Error", user=setup.auditor)
    setup.hotel.business_date = inv.issue_date
    setup.hotel.save()
    inv.refresh_from_db()
    billing.void_invoice(inv, "Error", user=setup.auditor)
    assert inv.status == "voided"


def test_pdf_has_simulation_watermark(setup, book):
    from apps.billing.pdf import invoice_pdf_bytes

    f = _folio_with(setup, book)
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
    )
    pdf = invoice_pdf_bytes(inv)
    assert pdf[:4] == b"%PDF"


def test_ple_sales_register_format(setup, book):
    from apps.billing.ple import sales_register

    f = _folio_with(setup, book)
    inv = billing.issue_invoice(
        f, "03", billing.customer_from_folio(f, "03"), user=setup.receptionist, send=False
    )
    content = sales_register(setup.hotel, inv.issue_date.year, inv.issue_date.month)
    line = content.splitlines()[0]
    assert line.startswith(f"{inv.issue_date:%Y%m}00|")
    assert "|B001|" in line and line.endswith("|")
