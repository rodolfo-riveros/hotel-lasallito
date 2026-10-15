"""Tarjetas de habitación y llamadas tarifadas (integraciones opcionales, fase 4)."""

import logging
import math
from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .adapters import classify, get_lock, parse_cdr, pbx_enabled
from .models import CallRecord, KeyCard

log = logging.getLogger(__name__)

# Tarifa por minuto iniciado, en soles (configurable con PBX_RATES en el .env como JSON).
DEFAULT_RATES = {
    "internal": "0",
    "local": "0.50",
    "mobile": "1.00",
    "national": "1.50",
    "international": "5.00",
}


def _validity(reservation):
    tz = timezone.get_current_timezone()
    start = timezone.now()
    end = timezone.make_aware(
        datetime.combine(
            reservation.departure,
            (
                reservation.property.check_out_time
                if isinstance(reservation.property.check_out_time, time)
                else time(12)
            ),
        ),
        tz,
    )
    return start, end


@transaction.atomic
def issue_keys(reservation, user=None, copies=2, replace=True) -> list[KeyCard]:
    """Graba tarjetas para la habitación de la reserva. Con `replace` anula las anteriores."""
    lock = get_lock()
    if lock is None or reservation.room is None:
        return []
    if replace:
        revoke_keys(reservation)
    start, end = _validity(reservation)
    result = lock.encode(reservation.room, start, end, copies)
    if not result.ok:
        raise RuntimeError(result.message)
    return [
        KeyCard.objects.create(
            property=reservation.property,
            reservation=reservation,
            room=reservation.room,
            card_ref=ref,
            valid_from=start,
            valid_to=end,
            issued_by=user,
            provider=lock.code,
        )
        for ref in result.card_refs
    ]


def revoke_keys(reservation) -> int:
    lock = get_lock()
    cards = list(KeyCard.objects.filter(reservation=reservation, status=KeyCard.Status.ACTIVE))
    for card in cards:
        if lock is None or lock.revoke(card):
            card.status = KeyCard.Status.REVOKED
            card.save(update_fields=["status"])
    return len(cards)


def safe(fn, *args, **kwargs):
    """Una falla de la cerradura no debe impedir el check-in: se registra y se avisa a recepción."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - cualquier falla del equipo externo
        log.warning("Integración %s falló: %s", fn.__name__, exc)
        reservation = args[0] if args else None
        if reservation is not None and hasattr(reservation, "property"):
            from apps.comms.services import notify_role

            notify_role(
                reservation.property,
                "receptionist",
                "Falla del codificador de tarjetas",
                str(exc)[:200],
                url=f"/reservas/{reservation.pk}/",
                level="warning",
            )
        return None


def rates() -> dict[str, Decimal]:
    custom = getattr(settings, "PBX_RATES", None) or {}
    return {k: Decimal(str(custom.get(k, v))) for k, v in DEFAULT_RATES.items()}


def call_cost(kind: str, seconds: int) -> Decimal:
    minutes = math.ceil(seconds / 60) if seconds > 0 else 0
    return (rates()[kind] * minutes).quantize(Decimal("0.01"))


@transaction.atomic
def register_call(property_obj, payload: dict) -> CallRecord | None:
    """Registra la llamada de la central y la carga al folio del huésped en esa habitación."""
    from apps.folio import services as folio
    from apps.reservations.models import Reservation
    from apps.rooms.models import Room

    if not pbx_enabled():
        return None
    data = parse_cdr(payload)
    started = data["started_at"]
    started = parse_datetime(started) if isinstance(started, str) else started
    if started is None:
        raise ValueError("Fecha de inicio inválida")
    if timezone.is_naive(started):
        started = timezone.make_aware(started)
    existing = CallRecord.objects.filter(property=property_obj, external_id=data["external_id"]).first()
    if existing is not None:
        return existing  # la central reenvía; no se cobra dos veces
    kind = classify(data["dialed"])
    room = Room.objects.filter(property=property_obj, number=data["extension"]).first()
    reservation = None
    if room is not None:
        reservation = Reservation.objects.filter(
            property=property_obj, room=room, status="checked_in"
        ).first()
    record = CallRecord(
        property=property_obj,
        external_id=data["external_id"],
        extension=data["extension"],
        room=room,
        reservation=reservation,
        dialed=data["dialed"],
        kind=kind,
        started_at=started,
        seconds=data["seconds"],
        cost=call_cost(kind, data["seconds"]),
    )
    try:
        with transaction.atomic():
            record.save()
    except IntegrityError:
        return CallRecord.objects.get(property=property_obj, external_id=data["external_id"])
    if reservation is not None and record.cost > 0:
        masked = data["dialed"][:-3] + "***" if len(data["dialed"]) > 5 else data["dialed"]
        record.charge = folio.post_charge(
            folio.main_folio(reservation),
            folio.get_concept(property_obj, "phone"),
            record.cost,
            description=f"Llamada {record.get_kind_display().lower()} {masked} ({math.ceil(record.seconds / 60)} min)",
            service_date=timezone.localtime(started).date(),
            source="phone",
            reference=f"CDR{record.external_id}"[:40],
        )
        record.save(update_fields=["charge"])
    return record
