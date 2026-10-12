"""Recepción, folio y caja: RF-REC-02/06/07/08/10/13, RF-TAR-06, RF-CAJ-01/02/04."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.folio import services as folio
from apps.folio.models import Charge, Payment
from apps.frontdesk import services as fd
from apps.frontdesk.models import NightAudit
from apps.housekeeping.models import CleaningTask
from apps.reservations.models import Reservation
from conftest import BUSINESS_DATE as D

pytestmark = pytest.mark.django_db


def _pay_all(r, user, method="card"):
    for f in r.folios.all():
        if f.balance > 0:
            folio.add_payment(f, method, f.balance, user=user)


def test_tax_split_igv_included(setup):
    lodging = folio.get_concept(setup.hotel, "lodging")
    split = folio.split_taxes(setup.hotel, lodging, Decimal("118.00"))
    assert (split.base, split.igv) == (Decimal("100.00"), Decimal("18.00"))
    exempt = folio.split_taxes(setup.hotel, lodging, Decimal("118.00"), exempt=True)
    assert (exempt.base, exempt.igv, exempt.exempt) == (Decimal("118.00"), Decimal("0"), True)
    fnb = folio.get_concept(setup.hotel, "fnb")
    assert folio.split_taxes(setup.hotel, fnb, Decimal("118.00"), exempt=True).igv == Decimal("18.00")


def test_check_in_assigns_room_and_signs_card_rf_rec_02(setup, book):
    r = book(nights=2)
    fd.check_in(
        r,
        user=setup.receptionist,
        signature="data:image/png;base64,AAA",
        document_verified=True,
        charge_early=False,
    )
    r.refresh_from_db()
    assert r.status == "checked_in" and r.room is not None
    assert r.registration_card.signed_at is not None


def test_cannot_check_in_dirty_room_unless_forced(setup, book):
    room = setup.rooms[0]
    room.hk_status = "dirty"
    room.save()
    r = book(room=room)
    with pytest.raises(ValidationError):
        fd.check_in(r, user=setup.receptionist, charge_early=False)
    fd.check_in(r, user=setup.receptionist, charge_early=False, allow_dirty=True)


def test_non_domiciled_exemption_requires_passport_and_entry_rf_tar_06(setup, book):
    r = book(guest=setup.peruvian)
    with pytest.raises(ValidationError):
        fd.check_in(r, user=setup.receptionist, validate_non_domiciled=True, charge_early=False)
    r2 = book(guest=setup.foreigner)
    fd.check_in(r2, user=setup.receptionist, validate_non_domiciled=True, charge_early=False)
    r2.refresh_from_db()
    assert r2.igv_exempt
    fd_charge = folio.post_charge(r2.main_folio, folio.get_concept(setup.hotel, "lodging"), Decimal("300"))
    assert fd_charge.tax_exempt and fd_charge.igv == 0
    bar = folio.post_charge(r2.main_folio, folio.get_concept(setup.hotel, "fnb"), Decimal("59"))
    assert bar.igv == Decimal("9.00")  # el IGV de restaurante no se exonera


def test_early_check_in_fee_rf_rec_07(setup, book):
    r = book()
    fd.check_in(r, user=setup.receptionist, charge_early=True)
    fee = Charge.objects.get(folio__reservation=r, source="early_checkin")
    assert fee.amount == Decimal("150.00")  # 50% de la noche


def test_check_out_requires_zero_balance_rf_rec_10(setup, book):
    r = book(nights=1)
    fd.check_in(r, user=setup.receptionist, charge_early=False)
    folio.post_charge(r.main_folio, folio.get_concept(setup.hotel, "laundry"), Decimal("25"))
    with pytest.raises(ValidationError):
        fd.check_out(r, user=setup.receptionist)
    _pay_all(r, setup.receptionist)
    fd.check_out(r, user=setup.receptionist)
    r.refresh_from_db()
    assert r.status == "checked_out"
    assert r.room.hk_status == "dirty"
    assert CleaningTask.objects.filter(room=r.room, kind="departure").exists()
    r.guest.refresh_from_db()
    assert r.guest.total_stays == 1


def test_walk_in_in_one_step_rf_rec_06(setup):
    r = fd.walk_in(
        setup.hotel,
        guest=setup.peruvian,
        room=setup.rooms[1],
        rate_plan=setup.rack,
        nights=2,
        user=setup.receptionist,
    )
    assert r.status == "checked_in" and r.channel == "walk_in"


def test_room_move_keeps_folio_rf_rec_08(setup, book):
    r = book(room=setup.rooms[0])
    fd.check_in(r, user=setup.receptionist, charge_early=False)
    folio_before = r.main_folio
    fd.move_room(r, setup.rooms[3], kind="upgrade", reason="Cortesía VIP", user=setup.manager)
    r.refresh_from_db()
    assert r.room == setup.rooms[3]
    assert r.main_folio == folio_before
    assert r.total_amount == Decimal("600.00")  # mantiene tarifa
    setup.rooms[0].refresh_from_db()
    assert setup.rooms[0].hk_status == "dirty"


def test_night_audit_posts_rooms_no_shows_and_advances_date_rf_rec_13(setup, book):
    in_house = book(nights=2)
    fd.check_in(in_house, user=setup.receptionist, charge_early=False)
    no_show = book(status="guaranteed")
    with pytest.raises(PermissionDenied):
        fd.run_night_audit(setup.hotel, user=setup.receptionist)
    record = fd.run_night_audit(setup.hotel, user=setup.auditor)
    assert record.summary["habitaciones_cargadas"] == 1
    assert no_show.code in record.summary["no_shows"]
    setup.hotel.refresh_from_db()
    assert setup.hotel.business_date == D + timedelta(days=1)
    charge = Charge.objects.get(folio__reservation=in_house, source="night_audit")
    assert (charge.amount, charge.igv) == (Decimal("300.00"), Decimal("45.76"))
    # No se puede cerrar dos veces el mismo día
    setup.hotel.business_date = D
    setup.hotel.save()
    with pytest.raises(ValidationError):
        fd.run_night_audit(setup.hotel, user=setup.auditor)
    assert NightAudit.objects.filter(property=setup.hotel).count() == 1


def test_cash_payment_requires_open_session_rf_caj_01(setup, book):
    r = book()
    with pytest.raises(ValidationError):
        folio.add_payment(r.main_folio, "cash_pen", Decimal("100"), user=setup.receptionist)
    session = folio.open_cash_session(setup.register, setup.receptionist, opening_pen=Decimal("200"))
    p = folio.add_payment(r.main_folio, "cash_pen", Decimal("100"), user=setup.receptionist)
    assert p.cash_session == session


def test_usd_cash_payment_converts_at_buy_rate_rf_caj_02(setup, book):
    r = book()
    folio.open_cash_session(setup.register, setup.receptionist)
    p = folio.add_payment(r.main_folio, "cash_usd", Decimal("100"), user=setup.receptionist)
    assert (p.currency, p.amount_original, p.amount) == ("USD", Decimal("100"), Decimal("370.00"))


def test_cash_close_reports_difference_rf_caj_01_04(setup, book):
    r = book()
    session = folio.open_cash_session(setup.register, setup.receptionist, opening_pen=Decimal("200"))
    folio.add_payment(r.main_folio, "cash_pen", Decimal("300"), user=setup.receptionist)
    folio.add_payment(r.main_folio, "yape", Decimal("50"), user=setup.receptionist)
    folio.add_petty_expense(session, "Taxi para huésped", Decimal("20"))
    folio.close_cash_session(session, {"cash_pen": "470", "yape": "50"}, setup.receptionist, "Faltan 10")
    session.refresh_from_db()
    assert session.expected["cash_pen"] == "480.00"
    assert session.difference == Decimal("-10.00")
    from apps.core.models import AuditLog

    assert AuditLog.objects.filter(action="cash_close", object_id=str(session.pk)).exists()


def test_voiding_charge_requires_permission_and_is_audited(setup, book):
    r = book()
    c = folio.post_charge(r.main_folio, folio.get_concept(setup.hotel, "laundry"), Decimal("30"))
    with pytest.raises(PermissionDenied):
        folio.void_charge(c, "Error", setup.receptionist)
    folio.void_charge(c, "Error de digitación", setup.auditor)
    assert r.main_folio.balance == 0


def test_split_folio_by_transferring_charges_rf_rec_09(setup, book):
    r = book()
    company_folio = folio.create_folio(setup.hotel, reservation=r, name="Empresa XYZ")
    c = folio.post_charge(r.main_folio, folio.get_concept(setup.hotel, "lodging"), Decimal("300"))
    folio.transfer_charge(c, company_folio, setup.receptionist)
    assert company_folio.balance == Decimal("300.00") and r.main_folio.balance == 0


def test_refund_is_negative_payment(setup, book):
    r = book()
    folio.add_payment(r.main_folio, "card", Decimal("100"), user=setup.receptionist)
    folio.add_payment(r.main_folio, "card", Decimal("40"), user=setup.receptionist, refund=True)
    assert r.main_folio.total_payments == Decimal("60.00")
    assert Payment.objects.filter(is_refund=True).count() == 1
    assert Reservation.objects.get(pk=r.pk).balance == Decimal("-60.00")
