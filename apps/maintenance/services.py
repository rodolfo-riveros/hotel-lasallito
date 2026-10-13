"""Órdenes de trabajo con bloqueo automático de la habitación y preventivo (RF-MAN-01 a 04)."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog, Sequence
from apps.rooms.models import Room, RoomBlock

from .models import PreventivePlan, WorkOrder, WorkOrderPart


@transaction.atomic
def open_work_order(property_obj, *, title, user=None, **fields) -> WorkOrder:
    wo = WorkOrder.objects.create(
        property=property_obj,
        number=f"OT{Sequence.next_value(property_obj, 'work_order'):05d}",
        title=title,
        **fields,
    )
    if wo.block_room and wo.room:
        _block(wo)
    from apps.comms.services import notify_role

    notify_role(
        property_obj,
        "maintenance",
        _("Nueva OT %(n)s: %(t)s") % {"n": wo.number, "t": title},
        _("Prioridad %(p)s%(r)s")
        % {"p": wo.get_priority_display(), "r": f" · hab. {wo.room.number}" if wo.room else ""},
        url=f"/mantenimiento/{wo.pk}/",
        level="warning" if wo.priority in ("high", "urgent") else "info",
    )
    audit.log(AuditLog.Action.CREATE, wo, user=user)
    return wo


def _block(wo: WorkOrder):
    """RF-MAN-03: bloquea la habitación desde hoy hasta que se cierre la orden."""
    from apps.reservations.availability import overlapping_reservations

    today = wo.property.current_business_date()
    occupied = [
        r
        for r in overlapping_reservations(wo.room, today, today + timedelta(days=1))
        if r.status == "checked_in"
    ]
    if occupied:
        raise ValidationError(_("La habitación está ocupada: reubique al huésped antes de bloquearla."))
    block = RoomBlock.objects.create(
        property=wo.property,
        room=wo.room,
        kind=RoomBlock.Kind.MAINTENANCE,
        start_date=today,
        end_date=today + timedelta(days=30),
        reason=f"{wo.number}: {wo.title}",
    )
    wo.room_block = block
    wo.save(update_fields=["room_block"])


@transaction.atomic
def start(wo: WorkOrder, user) -> WorkOrder:
    wo.status = WorkOrder.Status.IN_PROGRESS
    wo.started_at = wo.started_at or timezone.now()
    wo.assigned_to = wo.assigned_to or user
    wo.save()
    return wo


@transaction.atomic
def add_part(wo: WorkOrder, item, quantity, user=None) -> WorkOrderPart:
    """Repuestos: salen del almacén de mantenimiento al costo promedio."""
    from apps.inventory import services as inv
    from apps.inventory.models import StockMovement, Warehouse

    warehouse = (
        Warehouse.objects.filter(property=wo.property, kind="maintenance", is_active=True).first()
        or Warehouse.objects.filter(property=wo.property, is_active=True).first()
    )
    if warehouse is None:
        raise ValidationError(_("Configure un almacén."))
    mv = inv.issue(warehouse, item, quantity, kind=StockMovement.Kind.MAINTENANCE, reference=wo.number)
    return WorkOrderPart.objects.create(
        work_order=wo, item=item, quantity=Decimal(quantity), cost=-mv.total_cost
    )


@transaction.atomic
def close(wo: WorkOrder, user, resolution: str, labor_cost=Decimal("0")) -> WorkOrder:
    if not resolution:
        raise ValidationError(_("Describa la solución."))
    wo.status = WorkOrder.Status.DONE
    wo.closed_at = timezone.now()
    wo.resolution = resolution
    wo.labor_cost = Decimal(labor_cost or 0)
    wo.save()
    if wo.room_block_id:
        block = wo.room_block
        block.is_active = False
        block.end_date = max(block.start_date + timedelta(days=1), wo.property.current_business_date())
        block.save()
        Room.objects.filter(pk=wo.room_id).update(hk_status=Room.HKStatus.DIRTY)
        from apps.comms.services import notify_role

        notify_role(
            wo.property,
            "housekeeping",
            _("Hab. %(n)s liberada por mantenimiento") % {"n": wo.room.number},
            _("Requiere limpieza antes de venderse."),
            url="/housekeeping/",
        )
    audit.log(
        AuditLog.Action.UPDATE, wo, changes={"status": ["done"], "costo": str(wo.total_cost)}, user=user
    )
    return wo


def generate_preventive(property_obj, today=None) -> list[WorkOrder]:
    """RF-MAN-02: crea las órdenes de los planes vencidos y reprograma la siguiente fecha."""
    today = today or property_obj.current_business_date()
    created = []
    for plan in PreventivePlan.objects.filter(property=property_obj, is_active=True, next_due__lte=today):
        wo = open_work_order(
            property_obj,
            title=f"Preventivo: {plan.name}",
            description=plan.checklist,
            asset=plan.asset,
            room=plan.asset.room,
            source=WorkOrder.Source.PREVENTIVE,
            assigned_to=plan.assigned_to,
        )
        plan.next_due = today + timedelta(days=plan.frequency_days)
        plan.save(update_fields=["next_due"])
        created.append(wo)
    return created


def cost_history(property_obj):
    """RF-MAN-04: costo e historial por habitación y por equipo."""
    by_room = (
        WorkOrder.objects.filter(property=property_obj, room__isnull=False)
        .values("room__number")
        .annotate(n=Count("pk"), labor=Sum("labor_cost"), parts=Sum("parts__cost"))
        .order_by("room__number")
    )
    by_asset = (
        WorkOrder.objects.filter(property=property_obj, asset__isnull=False)
        .values("asset__code", "asset__name")
        .annotate(n=Count("pk"), labor=Sum("labor_cost"), parts=Sum("parts__cost"))
        .order_by("asset__code")
    )
    return list(by_room), list(by_asset)
