"""Reglas del almacén: costo promedio ponderado, salidas, transferencias, conteo y alertas.

RF-ALM-03/04/05/06/07/08, RF-POS-05 y RF-HK-05. Toda operación es atómica y
bloquea la fila de stock (`select_for_update`) para que dos salidas
simultáneas no dejen saldos inconsistentes.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog

from .models import Item, Lot, Stock, StockCount, StockCountLine, StockMovement, Warehouse, Waste

ZERO = Decimal("0")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")


def _stock(warehouse, item) -> Stock:
    stock, _created = Stock.objects.select_for_update().get_or_create(warehouse=warehouse, item=item)
    return stock


def _move(stock: Stock, kind, qty: Decimal, unit_cost: Decimal, *, date, reference="", notes="", lot=None):
    total = (qty * unit_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return StockMovement.objects.create(
        property=stock.warehouse.property,
        date=date,
        warehouse=stock.warehouse,
        item=stock.item,
        kind=kind,
        quantity=qty,
        unit_cost=unit_cost,
        total_cost=total,
        balance_qty=stock.quantity,
        balance_avg_cost=stock.avg_cost,
        reference=reference,
        notes=notes,
        lot=lot,
    )


@transaction.atomic
def receive(
    warehouse: Warehouse,
    item: Item,
    quantity,
    unit_cost,
    *,
    date=None,
    kind=StockMovement.Kind.PURCHASE,
    reference="",
    notes="",
    lot_code="",
    expiry=None,
) -> StockMovement:
    """Ingreso: recalcula el costo promedio ponderado (RF-ALM-04)."""
    qty = Decimal(quantity).quantize(Q3)
    cost = Decimal(unit_cost).quantize(Q4)
    if qty <= 0:
        raise ValidationError(_("La cantidad debe ser positiva."))
    if item.is_perishable and kind == StockMovement.Kind.PURCHASE and not expiry:
        raise ValidationError(
            _("%(i)s es perecible: indique lote y fecha de vencimiento.") % {"i": item.name}
        )
    stock = _stock(warehouse, item)
    old_value = stock.quantity * stock.avg_cost
    stock.quantity += qty
    stock.avg_cost = ((old_value + qty * cost) / stock.quantity).quantize(Q4) if stock.quantity > 0 else cost
    stock.save()
    Item.objects.filter(pk=item.pk).update(last_cost=cost)
    lot = None
    if lot_code or expiry:
        lot, _c = Lot.objects.get_or_create(
            warehouse=warehouse, item=item, code=lot_code or "S/L", defaults={"expiry_date": expiry}
        )
        Lot.objects.filter(pk=lot.pk).update(quantity=F("quantity") + qty)
    return _move(
        stock,
        kind,
        qty,
        cost,
        date=date or warehouse.property.current_business_date(),
        reference=reference,
        notes=notes,
        lot=lot,
    )


@transaction.atomic
def issue(
    warehouse: Warehouse,
    item: Item,
    quantity,
    *,
    kind=StockMovement.Kind.REQUISITION,
    date=None,
    reference="",
    notes="",
    allow_negative=False,
) -> StockMovement:
    """Salida al costo promedio vigente. Consume lotes por fecha de vencimiento (FEFO)."""
    qty = Decimal(quantity).quantize(Q3)
    if qty <= 0:
        raise ValidationError(_("La cantidad debe ser positiva."))
    stock = _stock(warehouse, item)
    if stock.quantity < qty and not allow_negative:
        raise ValidationError(
            _("Stock insuficiente de %(i)s en %(w)s: hay %(q)s.")
            % {"i": item.name, "w": warehouse, "q": stock.quantity}
        )
    stock.quantity -= qty
    stock.save()
    remaining = qty
    for lot in (
        Lot.objects.select_for_update()
        .filter(warehouse=warehouse, item=item, quantity__gt=0)
        .order_by("expiry_date")
    ):
        take = min(lot.quantity, remaining)
        lot.quantity -= take
        lot.save(update_fields=["quantity"])
        remaining -= take
        if remaining <= 0:
            break
    return _move(
        stock,
        kind,
        -qty,
        stock.avg_cost,
        date=date or warehouse.property.current_business_date(),
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def transfer(origin: Warehouse, target: Warehouse, item: Item, quantity, *, reference="", user=None):
    if origin.pk == target.pk:
        raise ValidationError(_("Elija almacenes distintos."))
    out = issue(
        origin,
        item,
        quantity,
        kind=StockMovement.Kind.TRANSFER_OUT,
        reference=reference,
        notes=_("Hacia %(w)s") % {"w": target},
    )
    receive(
        target,
        item,
        quantity,
        out.unit_cost,
        kind=StockMovement.Kind.TRANSFER_IN,
        reference=reference,
        notes=_("Desde %(w)s") % {"w": origin},
    )
    return out


@transaction.atomic
def adjust(warehouse, item, new_quantity, *, reason, user, reference="") -> StockMovement | None:
    """Ajuste con motivo (RF-ALM-03) y auditoría."""
    if not reason:
        raise ValidationError(_("Indique el motivo del ajuste."))
    stock = _stock(warehouse, item)
    diff = Decimal(new_quantity).quantize(Q3) - stock.quantity
    if diff == 0:
        return None
    if diff > 0:
        mv = receive(
            warehouse,
            item,
            diff,
            stock.avg_cost or item.last_cost,
            kind=StockMovement.Kind.ADJUST_IN,
            reference=reference,
            notes=reason,
        )
    else:
        mv = issue(
            warehouse, item, -diff, kind=StockMovement.Kind.ADJUST_OUT, reference=reference, notes=reason
        )
    audit.log(
        AuditLog.Action.UPDATE,
        mv,
        changes={"ajuste": str(diff)},
        reason=reason,
        user=user,
        property=warehouse.property,
    )
    return mv


def stock_of(warehouse, item) -> Decimal:
    s = Stock.objects.filter(warehouse=warehouse, item=item).first()
    return s.quantity if s else ZERO


# --------------------------------------------------------------------------
# Inventario físico (RF-ALM-06)
# --------------------------------------------------------------------------


@transaction.atomic
def start_count(warehouse: Warehouse, user=None) -> StockCount:
    count = StockCount.objects.create(
        property=warehouse.property, warehouse=warehouse, date=warehouse.property.current_business_date()
    )
    for s in Stock.objects.filter(warehouse=warehouse).select_related("item"):
        StockCountLine.objects.create(count=count, item=s.item, system_qty=s.quantity)
    return count


@transaction.atomic
def close_count(count: StockCount, user) -> list[StockMovement]:
    if count.status != StockCount.Status.OPEN:
        raise ValidationError(_("El conteo ya está cerrado."))
    moves = []
    for line in count.lines.select_related("item"):
        if line.counted_qty is None or line.difference == 0:
            continue
        mv = adjust(
            count.warehouse,
            line.item,
            line.counted_qty,
            reason=_("Inventario físico %(d)s") % {"d": count.date.strftime("%d/%m/%Y")},
            user=user,
            reference=f"INV{count.pk}",
        )
        if mv:
            moves.append(mv)
    count.status = StockCount.Status.CLOSED
    count.save(update_fields=["status"])
    return moves


# --------------------------------------------------------------------------
# Mermas (RF-ALM-08)
# --------------------------------------------------------------------------


@transaction.atomic
def decide_waste(waste: Waste, approve: bool, user) -> Waste:
    if not user.has_pms_perm(waste.property, "inventory.approve"):
        raise PermissionDenied(_("Solo el gerente aprueba mermas."))
    if waste.status != Waste.Status.PENDING:
        raise ValidationError(_("La merma ya fue revisada."))
    waste.status = Waste.Status.APPROVED if approve else Waste.Status.REJECTED
    waste.approved_by = user
    waste.save()
    if approve:
        issue(
            waste.warehouse,
            waste.item,
            waste.quantity,
            kind=StockMovement.Kind.WASTE,
            reference=f"MER{waste.pk}",
            notes=waste.reason,
        )
    audit.log(
        AuditLog.Action.APPROVE if approve else AuditLog.Action.VOID, waste, reason=waste.reason, user=user
    )
    return waste


# --------------------------------------------------------------------------
# Consumos automáticos (RF-POS-05, RF-HK-05)
# --------------------------------------------------------------------------


def _warehouse_of_kind(property_obj, kind):
    return (
        Warehouse.objects.filter(property=property_obj, kind=kind, is_active=True).first()
        or Warehouse.objects.filter(property=property_obj, is_active=True).first()
    )


@transaction.atomic
def consume_recipe(order, user=None) -> list[StockMovement]:
    """Descuenta los insumos de los platos vendidos (permite saldo negativo y alerta)."""
    from .models import RecipeLine

    moves = []
    for oi in order.items.exclude(status="void").select_related("menu_item"):
        kind = Warehouse.Kind.BAR if oi.station == "bar" else Warehouse.Kind.KITCHEN
        warehouse = getattr(order.outlet, "warehouse", None) or _warehouse_of_kind(order.property, kind)
        if warehouse is None:
            continue
        for line in RecipeLine.objects.filter(menu_item=oi.menu_item).select_related("item"):
            moves.append(
                issue(
                    warehouse,
                    line.item,
                    line.quantity * oi.quantity,
                    kind=StockMovement.Kind.POS,
                    reference=order.number,
                    notes=oi.menu_item.name,
                    allow_negative=True,
                )
            )
    _alert_low_stock(order.property, {m.item_id for m in moves})
    return moves


def consume_for_minibar(property_obj, item, qty, *, reference="", user=None):
    warehouse = _warehouse_of_kind(property_obj, Warehouse.Kind.HOUSEKEEPING)
    if warehouse is None:
        return None
    mv = issue(
        warehouse, item, qty, kind=StockMovement.Kind.MINIBAR, reference=reference, allow_negative=True
    )
    _alert_low_stock(property_obj, {item.pk})
    return mv


def _alert_low_stock(property_obj, item_ids):
    from apps.comms.services import notify_role

    for row in low_stock(property_obj).filter(item_id__in=item_ids):
        notify_role(
            property_obj,
            "storekeeper",
            _("Stock bajo: %(i)s") % {"i": row.item.name},
            _("Quedan %(q)s en %(w)s (mínimo %(m)s).")
            % {"q": row.quantity, "w": row.warehouse, "m": row.item.min_stock},
            url="/almacen/alertas/",
        )


# --------------------------------------------------------------------------
# Alertas (RF-ALM-05, RF-ALM-07)
# --------------------------------------------------------------------------


def low_stock(property_obj):
    return Stock.objects.filter(
        warehouse__property=property_obj, item__min_stock__gt=0, quantity__lt=F("item__min_stock")
    ).select_related("item", "warehouse")


def suggested_orders(property_obj):
    """Sugerencia de pedido: hasta el stock máximo, en unidades de compra (RF-ALM-07)."""
    rows = []
    totals = {
        r["item"]: r["q"]
        for r in Stock.objects.filter(warehouse__property=property_obj)
        .values("item")
        .annotate(q=Sum("quantity"))
    }
    for item in Item.objects.filter(property=property_obj, is_active=True, min_stock__gt=0):
        current = totals.get(item.pk, ZERO)
        if current < item.min_stock:
            target = item.max_stock or item.min_stock * 2
            need = target - current
            packs = (need / item.purchase_factor).quantize(Decimal("1"), rounding="ROUND_UP")
            rows.append(
                {
                    "item": item,
                    "current": current,
                    "need": need,
                    "packs": packs,
                    "cost": (need * item.last_cost).quantize(Decimal("0.01")),
                }
            )
    return rows


def expiring_lots(property_obj, days=7):
    today = property_obj.current_business_date()
    return Lot.objects.filter(
        warehouse__property=property_obj,
        quantity__gt=0,
        expiry_date__isnull=False,
        expiry_date__lte=today + timedelta(days=days),
    ).select_related("item", "warehouse")


def food_cost(property_obj, start, end):
    """Costo de alimentos y bebidas consumidos (RF-REP-03)."""
    return (
        StockMovement.objects.filter(
            property=property_obj, kind=StockMovement.Kind.POS, date__gte=start, date__lt=end
        ).aggregate(s=Sum("total_cost"))["s"]
        or ZERO
    )
