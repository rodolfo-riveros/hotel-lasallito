"""Reservas: RF-RES-01, 04, 06, 08, 09, 10; RNF-INT-01/02 (sin doble venta)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction

from apps.core.models import AuditLog
from apps.folio.models import Charge
from apps.reservations import services
from apps.reservations.availability import availability_grid, type_availability
from apps.reservations.models import GroupAllotment, GroupBlock, Reservation
from conftest import BUSINESS_DATE as D

pytestmark = pytest.mark.django_db


def test_create_reservation_prices_and_opens_folio_rf_res_01(setup, book):
    r = book(nights=3)
    assert r.code.startswith("LS")
    assert r.total_amount == Decimal("900.00")
    assert len(r.nightly_rates) == 3
    assert r.main_folio is not None
    assert AuditLog.objects.filter(action="create", object_id=str(r.pk)).exists()


def test_same_room_cannot_be_sold_twice_rnf_int_02(setup, book):
    room = setup.rooms[0]
    book(room=room, nights=3)
    with pytest.raises(ValidationError):
        book(room=room, arrival_offset=1, nights=2)


def test_back_to_back_stays_are_allowed(setup, book):
    room = setup.rooms[0]
    book(room=room, nights=2)
    second = book(room=room, arrival_offset=2, nights=2)
    assert second.room == room


def test_type_inventory_prevents_overbooking(setup, book):
    for _ in range(3):
        book()
    with pytest.raises(ValidationError):
        book()


def test_controlled_overbooking_needs_manager_rf_res_08(setup, book):
    setup.hotel.overbooking_limit = 1
    setup.hotel.save()
    for _ in range(3):
        book()
    with pytest.raises(ValidationError):
        book(allow_overbooking=True)  # recepcionista
    r = book(allow_overbooking=True, user=setup.manager)
    assert r.overbooked
    from apps.comms.models import Notification

    assert Notification.objects.filter(role_code="manager").exists()
    with pytest.raises(ValidationError):
        book(allow_overbooking=True, user=setup.manager)  # supera el límite


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Restricción de exclusión solo en PostgreSQL")
def test_database_rejects_overlap_even_bypassing_code(setup, book):
    room = setup.rooms[0]
    first = book(room=room, nights=3)
    second = book(nights=2)
    second.room = room
    second.arrival = first.arrival
    with pytest.raises(IntegrityError), transaction.atomic():
        Reservation.objects.filter(pk=second.pk).update(room=room)


def test_group_allotment_holds_inventory_rf_res_04(setup, book):
    group = GroupBlock.objects.create(
        property=setup.hotel,
        code="G1",
        name="Colegio",
        arrival=D,
        departure=D + timedelta(days=2),
        release_date=D,
        rate_plan=setup.rack,
    )
    GroupAllotment.objects.create(group=group, room_type=setup.double, quantity=2)
    assert type_availability(setup.hotel, setup.double, D, D + timedelta(days=2)) == 1
    book()
    with pytest.raises(ValidationError):
        book()  # quedan solo las del grupo
    member = book(group=group)
    assert member.group == group
    grid = availability_grid(setup.hotel, D, D + timedelta(days=1))
    # 3 habitaciones − 2 vendidas − 1 cupo del grupo aún sin vender
    assert grid[setup.double.pk][D] == 0


def test_cancel_within_free_period_has_no_penalty_rf_res_06(setup, book):
    r = book(arrival_offset=10)
    services.cancel_reservation(r, "Cambio de planes", user=setup.receptionist)
    r.refresh_from_db()
    assert r.status == "cancelled"
    assert r.cancellation_penalty == 0


def test_late_cancellation_charges_first_night_rf_res_06(setup, book):
    r = book(arrival_offset=1)
    services.cancel_reservation(r, "Vuelo cancelado", user=setup.receptionist)
    charge = Charge.objects.get(folio__reservation=r)
    assert charge.amount == Decimal("300.00")
    assert charge.source == "penalty"


def test_only_manager_can_waive_penalty(setup, book):
    r = book(arrival_offset=1)
    with pytest.raises(PermissionDenied):
        services.cancel_reservation(r, "x", user=setup.receptionist, waive_penalty=True)
    services.cancel_reservation(r, "Cortesía", user=setup.manager, waive_penalty=True)
    assert not Charge.objects.filter(folio__reservation=r).exists()


def test_discount_above_role_cap_requires_approval_rf_tar_07(setup, book):
    with pytest.raises(PermissionDenied):
        book(discount_percent=Decimal("20"))  # recepcionista: tope 5%
    r = book(discount_percent=Decimal("20"), user=setup.manager)
    assert r.total_amount == Decimal("480.00")
    assert AuditLog.objects.filter(action="discount", object_id=str(r.pk)).exists()


def test_auto_assign_respects_preferences_rf_res_09(setup, book):
    r = book(pref_quiet=True)
    services.auto_assign(r, user=setup.receptionist)
    assert r.room.number == "201"
    r2 = book(pref_view="mountain")
    services.auto_assign(r2)
    assert r2.room.number == "102"


def test_changes_are_kept_in_history_rf_res_10(setup, book):
    r = book(nights=2)
    services.move_reservation(r, departure=r.departure + timedelta(days=1), user=setup.receptionist)
    r.refresh_from_db()
    assert r.total_amount == Decimal("900.00")
    changes = [log.changes for log in services.history(r)]
    assert any("departure" in c for c in changes)


def test_blacklisted_guest_needs_approval(setup, book):
    setup.peruvian.is_blacklisted = True
    setup.peruvian.blacklist_reason = "Daños"
    setup.peruvian.save()
    with pytest.raises(ValidationError):
        book()
    assert book(user=setup.manager).pk


def test_no_show_charges_guaranteed_reservation(setup, book):
    r = book(status="guaranteed")
    services.mark_no_show(r)
    assert r.status == "no_show"
    assert Charge.objects.get(folio__reservation=r).amount == Decimal("300.00")
