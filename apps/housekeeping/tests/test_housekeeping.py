"""Housekeeping y POS: RF-HK-02/03/04/08, RF-POS-02/04/06."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.comms.models import Notification
from apps.frontdesk import services as fd
from apps.housekeeping import services as hk
from apps.housekeeping.models import CleaningTask
from apps.pos import services as pos
from apps.pos.models import MenuCategory, MenuItem, Outlet, Table
from conftest import BUSINESS_DATE as D

pytestmark = pytest.mark.django_db


def test_daily_plan_prioritizes_departures_and_arrivals_rf_hk_02(setup, book):
    leaving = book(room=setup.rooms[0], arrival_offset=-2, nights=2)
    leaving.status = "checked_in"
    leaving.save()
    staying = book(room=setup.rooms[1], arrival_offset=-1, nights=3)
    staying.status = "checked_in"
    staying.save()
    setup.rooms[2].hk_status = "dirty"
    setup.rooms[2].save()
    book(room=setup.rooms[2])  # llega hoy a una habitación sucia
    tasks = hk.generate_daily_tasks(setup.hotel, D)
    by_room = {t.room.number: t for t in tasks}
    assert by_room["101"].kind == "departure" and by_room["101"].priority == 1
    assert by_room["102"].kind == "stayover"
    assert by_room["201"].priority <= 2
    assert hk.generate_daily_tasks(setup.hotel, D)  # idempotente
    assert CleaningTask.objects.filter(date=D).count() == 3


def test_balanced_assignment(setup, make_user):
    for room in setup.rooms:
        hk.create_departure_task(room, D)
    maids = [make_user("ana", role="housekeeping"), make_user("rosa", role="housekeeping")]
    load = hk.assign_balanced(setup.hotel, D, maids)
    assert sorted(load.values()) == [4, 4]


def test_clean_inspect_flow_notifies_front_desk_rf_hk_04_08(setup):
    task = hk.create_departure_task(setup.rooms[0], D)
    hk.start_task(task, setup.receptionist)
    assert task.room.hk_status == "cleaning"
    hk.finish_task(task, setup.receptionist)
    assert task.room.hk_status == "clean" and task.minutes is not None
    assert Notification.objects.filter(role_code="receptionist").exists()
    with pytest.raises(ValidationError):
        hk.inspect_task(task, setup.manager, approved=False)
    hk.inspect_task(task, setup.manager, approved=False, notes="Falta toalla")
    assert task.room.hk_status == "dirty" and task.status == "rejected"


@pytest.fixture
def restaurant(setup):
    outlet = Outlet.objects.create(property=setup.hotel, name="Restaurante Inti")
    table = Table.objects.create(outlet=outlet, number="1")
    cat = MenuCategory.objects.create(property=setup.hotel, name="Fondos")
    lomo = MenuItem.objects.create(
        property=setup.hotel, category=cat, name="Lomo saltado", price=Decimal("45")
    )
    tea = MenuItem.objects.create(
        property=setup.hotel, category=cat, name="Mate de coca", price=Decimal("8"), station="bar"
    )
    lomo.outlets.add(outlet)
    tea.outlets.add(outlet)
    return outlet, table, lomo, tea


def test_order_to_kitchen_and_charge_to_room_rf_pos_02_04(setup, book, restaurant):
    outlet, table, lomo, tea = restaurant
    r = book()
    fd.check_in(r, user=setup.receptionist, charge_early=False)
    order = pos.open_order(outlet, user=setup.receptionist, table=table, covers=2)
    pos.add_item(order, lomo, 2)
    pos.add_item(order, tea, 1)
    assert pos.send_to_kitchen(order) == 2
    with pytest.raises(ValidationError):
        pos.charge_to_room(order, r, user=setup.receptionist)  # sin firma
    pos.charge_to_room(order, r, user=setup.receptionist, signature="data:image/png;base64,AA")
    assert r.main_folio.total_charges == Decimal("98.00")
    assert order.status == "closed"


def test_pay_order_with_split_methods_issues_boleta(setup, restaurant):
    outlet, table, lomo, _tea = restaurant
    from apps.folio import services as folio

    folio.open_cash_session(setup.register, setup.receptionist)
    order = pos.open_order(outlet, user=setup.receptionist, table=table)
    pos.add_item(order, lomo, 2)
    with pytest.raises(ValidationError):
        pos.pay_order(order, [("cash_pen", Decimal("50"))], user=setup.receptionist)
    order, invoice = pos.pay_order(
        order,
        [("cash_pen", Decimal("50")), ("yape", Decimal("45"))],
        user=setup.receptionist,
        tip=Decimal("5"),
    )
    assert invoice.total == Decimal("90.00")  # la propina no se factura
    assert order.settlement == "paid"


def test_split_order_rf_pos_02(setup, restaurant):
    outlet, table, lomo, tea = restaurant
    order = pos.open_order(outlet, user=setup.receptionist, table=table)
    a = pos.add_item(order, lomo)
    pos.add_item(order, tea)
    child = pos.split_order(order, [a.pk], setup.receptionist)
    assert child.total == Decimal("45") and order.total == Decimal("8")


def test_breakfast_list_only_includes_breakfast_plans_rf_pos_06(setup, book):
    r = book(arrival_offset=-1, nights=3)
    r.status = "checked_in"
    r.save()
    assert list(pos.breakfast_list(setup.hotel, D)) == [r]
    setup.rack.meal_plan = "RO"
    setup.rack.save()
    assert not pos.breakfast_list(setup.hotel, D).exists()
