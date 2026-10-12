"""Plan diario, asignación balanceada, flujo de limpieza e inspección (RF-HK-02 a RF-HK-08)."""

from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog
from apps.rooms.models import Room

from .models import CleaningTask, LinenMovement, LinenType


def _get_or_create_task(room, day, kind, priority=5, reason=""):
    try:
        with transaction.atomic():
            task, created = CleaningTask.objects.get_or_create(
                property=room.property,
                room=room,
                date=day,
                kind=kind,
                defaults={"priority": priority, "priority_reason": reason},
            )
    except IntegrityError:
        task, created = CleaningTask.objects.get(room=room, date=day, kind=kind), False
    if not created and priority < task.priority:
        task.priority, task.priority_reason = priority, reason
        task.save(update_fields=["priority", "priority_reason"])
    return task


def create_departure_task(room, day):
    return _get_or_create_task(room, day, CleaningTask.Kind.DEPARTURE, 1, _("Salida"))


def generate_daily_tasks(property_obj, day):
    """RF-HK-02: prioridad: salidas primero, llegadas tempranas y VIP, luego estadías."""
    from apps.reservations.models import Reservation

    created = []
    arrivals = {
        r.room_id: r
        for r in Reservation.objects.filter(
            property=property_obj,
            arrival=day,
            status__in=Reservation.PRE_ARRIVAL_STATUSES,
            room__isnull=False,
        ).select_related("guest")
    }
    for r in Reservation.objects.filter(
        property=property_obj, status=Reservation.Status.CHECKED_IN, room__isnull=False
    ).select_related("room", "guest"):
        if r.departure <= day:
            created.append(create_departure_task(r.room, day))
        else:
            vip = r.guest.is_vip
            created.append(
                _get_or_create_task(
                    r.room, day, CleaningTask.Kind.STAYOVER, 3 if vip else 4, _("VIP en casa") if vip else ""
                )
            )
    for room in Room.objects.filter(property=property_obj, is_active=True, hk_status=Room.HKStatus.DIRTY):
        arrival = arrivals.get(room.pk)
        if arrival is not None:
            early = arrival.eta and arrival.eta.hour < 12
            priority = 1 if early or arrival.guest.is_vip else 2
            reason = (
                _("Llegada temprana")
                if early
                else (_("Llegada VIP") if arrival.guest.is_vip else _("Llegada hoy"))
            )
            created.append(_get_or_create_task(room, day, CleaningTask.Kind.DEPARTURE, priority, reason))
        elif not CleaningTask.objects.filter(room=room, date=day).exists():
            created.append(_get_or_create_task(room, day, CleaningTask.Kind.DEPARTURE, 3, _("Sucia")))
    return created


def assign_balanced(property_obj, day, maids) -> dict:
    """RF-HK-02: reparte tareas sin asignar según carga (créditos) y cercanía por piso."""
    maids = list(maids)
    if not maids:
        raise ValidationError(_("No hay mucamas seleccionadas."))
    load = defaultdict(int)
    floors = defaultdict(set)
    for t in CleaningTask.objects.filter(
        property=property_obj, date=day, assigned_to__in=maids
    ).select_related("room"):
        load[t.assigned_to_id] += CleaningTask.CREDITS[t.kind]
        floors[t.assigned_to_id].add(t.room.floor)
    pending = (
        CleaningTask.objects.filter(property=property_obj, date=day, assigned_to__isnull=True)
        .select_related("room")
        .order_by("priority", "room__floor", "room__number")
    )
    for task in pending:
        best = min(maids, key=lambda m: (load[m.pk] - (1 if task.room.floor in floors[m.pk] else 0), m.pk))
        task.assigned_to = best
        task.save(update_fields=["assigned_to"])
        load[best.pk] += CleaningTask.CREDITS[task.kind]
        floors[best.pk].add(task.room.floor)
    return {m.pk: load[m.pk] for m in maids}


@transaction.atomic
def start_task(task: CleaningTask, user):
    if task.status not in (CleaningTask.Status.PENDING, CleaningTask.Status.REJECTED):
        raise ValidationError(_("La tarea ya comenzó."))
    task.status = CleaningTask.Status.IN_PROGRESS
    task.started_at = timezone.now()
    task.assigned_to = task.assigned_to or user
    task.save()
    task.room.hk_status = Room.HKStatus.CLEANING
    task.room.save(update_fields=["hk_status"])
    return task


@transaction.atomic
def finish_task(task: CleaningTask, user, checklist: dict | None = None, notes=""):
    """RF-HK-03/08: registra tiempos y avisa a recepción."""
    if task.status != CleaningTask.Status.IN_PROGRESS:
        raise ValidationError(_("Inicie la tarea antes de terminarla."))
    task.checklist = checklist or {i: True for i in [c["label"] for c in task.checklist_items]}
    task.status = CleaningTask.Status.DONE
    task.finished_at = timezone.now()
    task.notes = notes
    task.save()
    task.room.hk_status = Room.HKStatus.CLEAN
    task.room.save(update_fields=["hk_status"])
    from apps.comms.services import notify_role

    for role in ("receptionist", "night_auditor"):
        notify_role(
            task.property,
            role,
            _("Habitación %(n)s limpia") % {"n": task.room.number},
            _("Lista para inspección o venta."),
            url="/habitaciones/",
        )
    notify_role(
        task.property, "housekeeping", _("Inspeccionar %(n)s") % {"n": task.room.number}, url="/housekeeping/"
    )
    return task


@transaction.atomic
def inspect_task(task: CleaningTask, user, approved: bool, notes="", photo=None):
    """RF-HK-04: inspección de la gobernanta con aprobación o rechazo y fotos."""
    if task.status != CleaningTask.Status.DONE:
        raise ValidationError(_("Solo se inspeccionan tareas terminadas."))
    task.inspected_by = user
    task.inspected_at = timezone.now()
    task.inspection_notes = notes
    if photo:
        task.inspection_photo = photo
    if approved:
        task.status = CleaningTask.Status.INSPECTED
        task.room.hk_status = Room.HKStatus.INSPECTED
    else:
        if not notes:
            raise ValidationError(_("Indique qué falta corregir."))
        task.status = CleaningTask.Status.REJECTED
        task.room.hk_status = Room.HKStatus.DIRTY
    task.save()
    task.room.save(update_fields=["hk_status"])
    audit.log(AuditLog.Action.APPROVE if approved else AuditLog.Action.VOID, task, reason=notes, user=user)
    return task


def linen_stock(property_obj):
    """Stock por tipo: en circulación y en lavandería (RF-HK-07)."""
    result = []
    for linen in LinenType.objects.filter(property=property_obj, is_active=True):
        sums = {
            row["direction"]: row["q"]
            for row in linen.movements.values("direction").annotate(q=Sum("quantity"))
        }
        purchased = sums.get(LinenMovement.Direction.PURCHASE, 0)
        discarded = sums.get(LinenMovement.Direction.DISCARD, 0)
        at_laundry = sums.get(LinenMovement.Direction.TO_LAUNDRY, 0) - sums.get(
            LinenMovement.Direction.FROM_LAUNDRY, 0
        )
        total = purchased - discarded
        result.append(
            {
                "linen": linen,
                "total": total,
                "at_laundry": at_laundry,
                "available": total - at_laundry,
                "below_par": total - at_laundry < linen.par_level,
            }
        )
    return result


@transaction.atomic
def post_minibar(reservation, items: list[tuple], user):
    """RF-HK-05: cargo de minibar al folio (y salida de almacén si está vinculado)."""
    from apps.folio import services as folio_services

    folio = folio_services.main_folio(reservation)
    concept = folio_services.get_concept(reservation.property, "minibar")
    charges = []
    for item, qty in items:
        if qty <= 0:
            continue
        charges.append(
            folio_services.post_charge(
                folio,
                concept,
                item.price,
                quantity=qty,
                description=f"Minibar: {item.name}",
                source="minibar",
            )
        )
        if getattr(item, "inventory_item_id", None):
            from apps.inventory.services import consume_for_minibar

            consume_for_minibar(
                reservation.property, item.inventory_item, qty, reference=reservation.code, user=user
            )
    return charges
