"""Disponibilidad por habitación y por tipo (RF-RES-02, RF-WEB-01, RF-CHA-02)."""

from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Q

from apps.rooms.models import Room, RoomBlock, RoomType

from .models import GroupBlock, Reservation


def overlapping_reservations(room, arrival, departure, exclude_pk=None):
    qs = Reservation.objects.filter(
        room=room, status__in=Reservation.ACTIVE_STATUSES, arrival__lt=departure, departure__gt=arrival
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return list(qs)


def room_is_blocked(room, arrival, departure) -> bool:
    return RoomBlock.objects.filter(
        room=room, is_active=True, start_date__lt=departure, end_date__gt=arrival
    ).exists()


def room_is_free(room, arrival, departure, exclude_pk=None) -> bool:
    return (
        room.is_active
        and not room_is_blocked(room, arrival, departure)
        and not overlapping_reservations(room, arrival, departure, exclude_pk)
    )


def free_rooms(property_obj, arrival, departure, room_type=None, exclude_pk=None):
    rooms = Room.objects.filter(property=property_obj, is_active=True)
    if room_type is not None:
        rooms = rooms.filter(room_type=room_type)
    busy = Reservation.objects.filter(
        property=property_obj,
        room__isnull=False,
        status__in=Reservation.ACTIVE_STATUSES,
        arrival__lt=departure,
        departure__gt=arrival,
    )
    if exclude_pk:
        busy = busy.exclude(pk=exclude_pk)
    blocked = RoomBlock.objects.filter(
        property=property_obj, is_active=True, start_date__lt=departure, end_date__gt=arrival
    )
    return (
        rooms.exclude(pk__in=busy.values("room_id"))
        .exclude(pk__in=blocked.values("room_id"))
        .select_related("room_type")
    )


def _days(start: date, end: date):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def availability_grid(property_obj, start: date, end: date, exclude_pk=None, include_groups=True):
    """Habitaciones libres por tipo y noche: {room_type_id: {date: libres}}.

    Descuenta reservas activas (asignadas o no), bloqueos y los cupos de grupos
    aún no vendidos hasta su fecha de liberación (RF-RES-04).
    """
    types = list(RoomType.objects.filter(property=property_obj, is_active=True))
    totals = defaultdict(int)
    for r in Room.objects.filter(property=property_obj, is_active=True).values("room_type_id"):
        totals[r["room_type_id"]] += 1
    grid = {t.pk: {d: totals[t.pk] for d in _days(start, end)} for t in types}

    blocks = RoomBlock.objects.filter(
        property=property_obj, is_active=True, start_date__lt=end, end_date__gt=start
    ).select_related("room")
    for b in blocks:
        for d in _days(max(b.start_date, start), min(b.end_date, end)):
            if b.room.room_type_id in grid:
                grid[b.room.room_type_id][d] -= 1

    reservations = Reservation.objects.filter(
        property=property_obj, status__in=Reservation.ACTIVE_STATUSES, arrival__lt=end, departure__gt=start
    )
    if exclude_pk:
        reservations = reservations.exclude(pk=exclude_pk)
    picked_up = defaultdict(int)  # (group, room_type, date) -> vendidas
    for r in reservations.values("room_type_id", "arrival", "departure", "group_id"):
        for d in _days(max(r["arrival"], start), min(r["departure"], end)):
            if r["room_type_id"] in grid:
                grid[r["room_type_id"]][d] -= 1
            if r["group_id"]:
                picked_up[(r["group_id"], r["room_type_id"], d)] += 1

    if include_groups:
        today = property_obj.current_business_date()
        groups = GroupBlock.objects.filter(
            property=property_obj,
            status__in=[GroupBlock.Status.TENTATIVE, GroupBlock.Status.DEFINITE],
            release_date__gte=today,
            arrival__lt=end,
            departure__gt=start,
        ).prefetch_related("allotments")
        for g in groups:
            for a in g.allotments.all():
                for d in _days(max(g.arrival, start), min(g.departure, end)):
                    pending = a.quantity - picked_up[(g.pk, a.room_type_id, d)]
                    if pending > 0 and a.room_type_id in grid:
                        grid[a.room_type_id][d] -= pending
    return grid


def type_availability(property_obj, room_type, arrival, departure, exclude_pk=None, group=None) -> int:
    """Mínimo de habitaciones libres de un tipo en todas las noches de la estadía."""
    grid = availability_grid(property_obj, arrival, departure, exclude_pk=exclude_pk)
    free = min(grid.get(room_type.pk, {arrival: 0}).values(), default=0)
    if group is not None:
        # El cupo del propio grupo está disponible para sus integrantes.
        allot = group.allotments.filter(room_type=room_type).first()
        if allot:
            sold = Reservation.objects.filter(
                group=group, room_type=room_type, status__in=Reservation.ACTIVE_STATUSES
            )
            if exclude_pk:
                sold = sold.exclude(pk=exclude_pk)
            free += max(0, allot.quantity - sold.count())
    return free


def arrivals_without_room(property_obj, day):
    return Reservation.objects.filter(
        property=property_obj, arrival=day, room__isnull=True, status__in=Reservation.PRE_ARRIVAL_STATUSES
    )


def occupancy_query(property_obj, start, end):
    return Reservation.objects.filter(
        Q(property=property_obj),
        Q(status__in=Reservation.OCCUPYING_STATUSES),
        Q(arrival__lt=end),
        Q(departure__gt=start),
    )
