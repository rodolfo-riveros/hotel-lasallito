"""Estado combinado de habitaciones: ocupación + limpieza + bloqueos (RF-HK-01, RNF-UX-04)."""

from .models import Room, RoomBlock


def room_status_key(room, occupied: bool, blocked) -> str:
    if blocked is not None:
        return "out_of_order" if blocked.kind == RoomBlock.Kind.OUT_OF_ORDER else "out_of_service"
    if occupied:
        return "occupied_dirty" if room.hk_status == Room.HKStatus.DIRTY else "occupied_clean"
    return {
        Room.HKStatus.CLEANING: "cleaning",
        Room.HKStatus.INSPECTED: "inspected",
        Room.HKStatus.DIRTY: "vacant_dirty",
    }.get(room.hk_status, "vacant_clean")


def room_board(property_obj, date=None):
    """Habitaciones con su estado, huésped actual y llegada del día."""
    from apps.reservations.models import Reservation

    date = date or property_obj.current_business_date()
    rooms = list(
        Room.objects.filter(property=property_obj, is_active=True)
        .select_related("room_type")
        .order_by("floor", "sort_order", "number")
    )
    blocks = {
        b.room_id: b
        for b in RoomBlock.objects.filter(
            property=property_obj, is_active=True, start_date__lte=date, end_date__gt=date
        )
    }
    in_house = {
        r.room_id: r
        for r in Reservation.objects.filter(
            property=property_obj, status=Reservation.Status.CHECKED_IN, room__isnull=False
        ).select_related("guest")
    }
    arrivals = {
        r.room_id: r
        for r in Reservation.objects.filter(
            property=property_obj,
            arrival=date,
            status__in=Reservation.PRE_ARRIVAL_STATUSES,
            room__isnull=False,
        ).select_related("guest")
    }
    board = []
    for room in rooms:
        current = in_house.get(room.pk)
        board.append(
            {
                "room": room,
                "status": room_status_key(room, current is not None, blocks.get(room.pk)),
                "block": blocks.get(room.pk),
                "guest_reservation": current,
                "arrival": arrivals.get(room.pk),
                "departing": current is not None and current.departure <= date,
            }
        )
    return board


def summary(board) -> dict:
    counts = {}
    for item in board:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts
