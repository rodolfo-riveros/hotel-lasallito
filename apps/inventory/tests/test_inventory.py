"""Almacén: RF-ALM-03/04/05/06/07/08, RF-POS-05, RF-HK-05."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.inventory import services as inv
from apps.inventory.models import Item, RecipeLine, StockMovement, Warehouse, Waste

pytestmark = pytest.mark.django_db


@pytest.fixture
def store(setup):
    kitchen = Warehouse.objects.create(property=setup.hotel, code="COC", name="Cocina", kind="kitchen")
    general = Warehouse.objects.create(property=setup.hotel, code="GEN", name="General", kind="general")
    hk = Warehouse.objects.create(property=setup.hotel, code="HK", name="HK", kind="housekeeping")
    rice = Item.objects.create(
        property=setup.hotel,
        code="ARROZ",
        name="Arroz",
        unit="g",
        min_stock=1000,
        max_stock=5000,
        purchase_factor=1000,
    )
    fish = Item.objects.create(
        property=setup.hotel, code="TRUCHA", name="Trucha", unit="g", is_perishable=True
    )
    water = Item.objects.create(property=setup.hotel, code="AGUA", name="Agua", unit="und")
    return kitchen, general, hk, rice, fish, water


def test_weighted_average_cost_rf_alm_04(store):
    kitchen, _g, _h, rice, _f, _w = store
    inv.receive(kitchen, rice, 1000, Decimal("0.004"))
    mv = inv.receive(kitchen, rice, 3000, Decimal("0.006"))
    assert mv.balance_qty == Decimal("4000")
    assert mv.balance_avg_cost == Decimal("0.0055")  # (4 + 18) / 4000
    out = inv.issue(kitchen, rice, 500)
    assert out.unit_cost == Decimal("0.0055") and out.total_cost == Decimal("-2.75")
    assert inv.stock_of(kitchen, rice) == Decimal("3500")


def test_cannot_issue_more_than_stock(store):
    kitchen, _g, _h, rice, _f, _w = store
    inv.receive(kitchen, rice, 100, 1)
    with pytest.raises(ValidationError):
        inv.issue(kitchen, rice, 200)


def test_transfer_keeps_cost_rf_alm_03(store):
    kitchen, general, _h, rice, _f, _w = store
    inv.receive(general, rice, 2000, Decimal("0.005"))
    inv.transfer(general, kitchen, rice, 500)
    assert inv.stock_of(kitchen, rice) == 500 and inv.stock_of(general, rice) == 1500
    assert StockMovement.objects.get(warehouse=kitchen, kind="transfer_in").unit_cost == Decimal("0.005")


def test_perishable_requires_expiry_and_fefo_rf_alm_05(store, setup):
    kitchen, _g, _h, _r, fish, _w = store
    with pytest.raises(ValidationError):
        inv.receive(kitchen, fish, 1000, Decimal("0.03"))
    d = setup.hotel.current_business_date()
    inv.receive(kitchen, fish, 1000, Decimal("0.03"), lot_code="B", expiry=d + timedelta(days=10))
    inv.receive(kitchen, fish, 1000, Decimal("0.03"), lot_code="A", expiry=d + timedelta(days=2))
    inv.issue(kitchen, fish, 1200)
    lots = {lot.code: lot.quantity for lot in fish.lots.all()}
    assert lots == {"A": 0, "B": 800}  # vence primero, sale primero
    assert list(inv.expiring_lots(setup.hotel, 7)) == []  # A ya se agotó


def test_low_stock_and_suggested_order_rf_alm_07(store, setup):
    kitchen, _g, _h, rice, _f, _w = store
    inv.receive(kitchen, rice, 400, 1)
    assert [s.item for s in inv.low_stock(setup.hotel)] == [rice]
    row = inv.suggested_orders(setup.hotel)[0]
    assert row["need"] == Decimal("4600") and row["packs"] == Decimal("5")  # sacos de 1000 g


def test_physical_count_adjusts_differences_rf_alm_06(store, setup):
    kitchen, _g, _h, rice, _f, _w = store
    inv.receive(kitchen, rice, 1000, 1)
    count = inv.start_count(kitchen)
    line = count.lines.get(item=rice)
    line.counted_qty = Decimal("950")
    line.save()
    moves = inv.close_count(count, setup.manager)
    assert len(moves) == 1 and moves[0].kind == "adjust_out"
    assert inv.stock_of(kitchen, rice) == 950


def test_waste_needs_manager_approval_rf_alm_08(store, setup, make_user):
    kitchen, _g, _h, rice, _f, _w = store
    inv.receive(kitchen, rice, 1000, 1)
    waste = Waste.objects.create(
        property=setup.hotel, warehouse=kitchen, item=rice, quantity=100, reason="Humedad"
    )
    storekeeper = make_user("almacen", role="storekeeper")
    with pytest.raises(PermissionDenied):
        inv.decide_waste(waste, True, storekeeper)
    inv.decide_waste(waste, True, setup.manager)
    assert inv.stock_of(kitchen, rice) == 900


def test_restaurant_sale_consumes_recipe_rf_pos_05(store, setup, book):
    from apps.frontdesk import services as fd
    from apps.pos import services as pos
    from apps.pos.models import MenuCategory, MenuItem, Outlet

    kitchen, _g, _h, rice, _f, _w = store
    inv.receive(kitchen, rice, 1000, Decimal("0.005"))
    outlet = Outlet.objects.create(property=setup.hotel, name="Resto", warehouse=kitchen)
    cat = MenuCategory.objects.create(property=setup.hotel, name="Fondos")
    dish = MenuItem.objects.create(
        property=setup.hotel, category=cat, name="Arroz chaufa", price=Decimal("30")
    )
    dish.outlets.add(outlet)
    RecipeLine.objects.create(menu_item=dish, item=rice, quantity=150)
    r = book()
    fd.check_in(r, user=setup.receptionist, charge_early=False)
    order = pos.open_order(outlet, user=setup.receptionist)
    pos.add_item(order, dish, 2)
    pos.charge_to_room(order, r, user=setup.receptionist, signature="x")
    assert inv.stock_of(kitchen, rice) == 700
    assert inv.food_cost(
        setup.hotel,
        setup.hotel.current_business_date(),
        setup.hotel.current_business_date() + timedelta(days=1),
    ) == Decimal("-1.50")


def test_minibar_consumes_housekeeping_stock_rf_hk_05(store, setup, book):
    from apps.housekeeping.models import MinibarItem
    from apps.housekeeping.services import post_minibar

    _k, _g, hk, _r, _f, water = store
    inv.receive(hk, water, 10, Decimal("1.8"))
    item = MinibarItem.objects.create(
        property=setup.hotel, name="Agua", price=Decimal("6"), inventory_item=water
    )
    r = book()
    post_minibar(r, [(item, 2)], setup.receptionist)
    assert inv.stock_of(hk, water) == 8
    assert r.main_folio.total_charges == Decimal("12.00")
