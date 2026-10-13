"""Compras y mantenimiento: RF-COM-01 a 05, RF-MAN-01 a 04."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.billing.validators import ruc_check_digit
from apps.inventory import services as inv
from apps.inventory.models import Item, Warehouse
from apps.maintenance import services as mnt
from apps.maintenance.models import Asset, PreventivePlan
from apps.purchasing import services as pur
from apps.purchasing.models import (
    Quotation,
    QuotationLine,
    Requisition,
    RequisitionLine,
    Supplier,
    SupplierInvoice,
)
from apps.rooms.models import RoomBlock

pytestmark = pytest.mark.django_db


def _ruc(p):
    return p + str(ruc_check_digit(p))


@pytest.fixture
def buying(setup, make_user):
    wh = Warehouse.objects.create(property=setup.hotel, code="GEN", name="General")
    rice = Item.objects.create(
        property=setup.hotel,
        code="ARROZ",
        name="Arroz",
        unit="g",
        purchase_factor=50000,
        purchase_unit="saco",
    )
    sup = Supplier.objects.create(
        property=setup.hotel, ruc=_ruc("2060555111"), name="Distribuidora", payment_days=15
    )
    sup2 = Supplier.objects.create(property=setup.hotel, ruc=_ruc("2060555222"), name="Mayorista")
    buyer = make_user("compras", role="purchasing")
    req = Requisition.objects.create(property=setup.hotel, number="RQ1", warehouse=wh)
    RequisitionLine.objects.create(requisition=req, item=rice, quantity=4, estimated_cost=Decimal("200"))
    return wh, rice, sup, sup2, buyer, req


def test_supplier_ruc_is_validated_rf_com_04():
    with pytest.raises(ValidationError):
        pur.validate_supplier_ruc("20100070971")
    pur.validate_supplier_ruc("20100070970")


def test_approval_by_amount_rf_com_01(buying, setup):
    _wh, _rice, _s, _s2, buyer, req = buying
    pur.submit(req, buyer)
    assert req.estimated_total == Decimal("800.00")
    assert pur.can_approve(buyer, setup.hotel, Decimal("800"))  # límite 2 000 del rol Compras
    assert not pur.can_approve(buyer, setup.hotel, Decimal("2500"))
    assert not pur.can_approve(setup.receptionist, setup.hotel, Decimal("10"))
    assert pur.can_approve(setup.manager, setup.hotel, Decimal("99999"))  # gerente sin límite
    RequisitionLine.objects.filter(requisition=req).update(estimated_cost=Decimal("700"))
    with pytest.raises(PermissionDenied):
        pur.decide(req, buyer, True)
    pur.decide(req, setup.manager, True)
    assert req.status == "approved"


def test_quotations_order_and_partial_receipt_rf_com_02_03_05(buying, setup):
    wh, rice, sup, sup2, buyer, req = buying
    pur.submit(req, buyer)
    pur.decide(req, setup.manager, True)
    q1 = Quotation.objects.create(requisition=req, supplier=sup, delivery_days=2)
    QuotationLine.objects.create(quotation=q1, item=rice, quantity=4, unit_price=Decimal("190"))
    q2 = Quotation.objects.create(requisition=req, supplier=sup2, delivery_days=1)
    QuotationLine.objects.create(quotation=q2, item=rice, quantity=4, unit_price=Decimal("210"))
    po = pur.order_from_quotation(q1, buyer)
    assert po.total == Decimal("760.00") and po.supplier == sup
    line = po.lines.get()
    pur.receive_goods(po, {line.pk: Decimal("1")}, user=buyer, guide="T001-1", invoice="F001-9")
    po.refresh_from_db()
    assert po.status == "partial"
    assert inv.stock_of(wh, rice) == Decimal("50000")  # 1 saco = 50 000 g
    assert rice.stocks.get().avg_cost == Decimal("0.0038")  # 190 / 50 000
    with pytest.raises(ValidationError):
        pur.receive_goods(po, {line.pk: Decimal("5")}, user=buyer)
    pur.receive_goods(po, {line.pk: Decimal("3")}, user=buyer)
    po.refresh_from_db()
    assert po.status == "received"
    payable = pur.register_invoice(po, "F001-9", Decimal("896.80"))
    assert (payable.due_date - payable.issue_date).days == 15
    assert SupplierInvoice.objects.filter(paid=False).count() == 1


def test_work_order_blocks_and_releases_room_rf_man_01_03(setup):
    room = setup.rooms[0]
    wo = mnt.open_work_order(
        setup.hotel, title="Terma no calienta", room=room, block_room=True, priority="high"
    )
    assert RoomBlock.objects.filter(room=room, is_active=True).exists()
    from apps.reservations.availability import room_is_free

    d = setup.hotel.current_business_date()
    assert not room_is_free(room, d, d.replace(day=d.day + 1))
    with pytest.raises(ValidationError):
        mnt.close(wo, setup.manager, "")
    mnt.close(wo, setup.manager, "Se cambió la resistencia", Decimal("60"))
    room.refresh_from_db()
    assert not RoomBlock.objects.filter(room=room, is_active=True).exists()
    assert room.hk_status == "dirty"


def test_parts_come_out_of_maintenance_store_rf_man_04(setup):
    wh = Warehouse.objects.create(property=setup.hotel, code="MAN", name="Mant.", kind="maintenance")
    part = Item.objects.create(property=setup.hotel, code="RES", name="Resistencia")
    inv.receive(wh, part, 2, Decimal("45"))
    wo = mnt.open_work_order(setup.hotel, title="Terma")
    mnt.add_part(wo, part, 1)
    assert wo.materials_cost == Decimal("45.00")
    mnt.close(wo, setup.manager, "Listo", Decimal("30"))
    assert wo.total_cost == Decimal("75.00")
    by_room, by_asset = mnt.cost_history(setup.hotel)
    assert by_room == [] and by_asset == []


def test_preventive_plans_generate_orders_rf_man_02(setup):
    asset = Asset.objects.create(property=setup.hotel, code="EXT", name="Extintor", kind="extinguisher")
    d = setup.hotel.current_business_date()
    plan = PreventivePlan.objects.create(
        property=setup.hotel, asset=asset, name="Recarga", frequency_days=180, next_due=d
    )
    created = mnt.generate_preventive(setup.hotel)
    assert len(created) == 1 and created[0].source == "preventive"
    plan.refresh_from_db()
    assert (plan.next_due - d).days == 180
    assert mnt.generate_preventive(setup.hotel) == []
