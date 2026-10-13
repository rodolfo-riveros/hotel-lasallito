"""Sincronización de disponibilidad, tarifas y reservas con los canales (RF-CHA-01 a 04, RNF-REN-03).

- Cada cambio de inventario (reserva, cancelación, bloqueo) marca la propiedad
  como "pendiente de publicar"; el programador publica en menos de 60 s y
  también se puede publicar a mano desde el panel.
- Las reservas que llegan de un canal se crean con el flujo normal del PMS, por
  lo que bajan la disponibilidad en todos los demás canales.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import AuditLog

from .adapters import get_adapter
from .models import Channel, SyncLog

HORIZON_DAYS = 90
DIRTY_KEY = "pms:channels:dirty:{pk}"


def mark_dirty(property_obj) -> None:
    cache.set(DIRTY_KEY.format(pk=property_obj.pk), True, 24 * 3600)


def is_dirty(property_obj) -> bool:
    return bool(cache.get(DIRTY_KEY.format(pk=property_obj.pk)))


def build_rows(channel: Channel, start: date, end: date) -> list[dict]:
    from apps.rates.services import quote
    from apps.reservations.availability import availability_grid

    grid = availability_grid(channel.property, start, end)
    mappings = {m.room_type_id: m for m in channel.room_mappings.select_related("room_type")}
    rate_map = channel.rate_mappings.select_related("rate_plan").first()
    rows = []
    for rt_id, mapping in mappings.items():
        for day, free in grid.get(rt_id, {}).items():
            price = None
            if rate_map:
                q = quote(
                    rate_map.rate_plan,
                    mapping.room_type,
                    day,
                    day + timedelta(days=1),
                    adults=mapping.room_type.base_occupancy,
                    check_restrictions=False,
                )
                if q.ok and q.nights:
                    price = (q.nights[0].amount * (100 + rate_map.markup_percent) / 100).quantize(
                        Decimal("0.01")
                    )
            rows.append(
                {
                    "room_type_id": rt_id,
                    "external": mapping.external_code,
                    "date": day,
                    "available": max(0, free),
                    "price": price,
                }
            )
    return rows


def push_channel(channel: Channel, start: date | None = None, days: int = HORIZON_DAYS) -> SyncLog:
    start = start or channel.property.current_business_date()
    end = start + timedelta(days=days)
    log = SyncLog.objects.create(
        property=channel.property,
        channel=channel,
        direction=SyncLog.Direction.PUSH,
        date_from=start,
        date_to=end,
    )
    return _run_push(log)


def _run_push(log: SyncLog) -> SyncLog:
    channel = log.channel
    log.attempts += 1
    try:
        rows = build_rows(channel, log.date_from, log.date_to)
        result = get_adapter().push(channel, rows)
    except Exception as exc:  # noqa: BLE001 - se registra cualquier falla del proveedor
        result = type("R", (), {"ok": False, "message": str(exc)[:250]})()
        rows = []
    log.status = SyncLog.Status.OK if result.ok else SyncLog.Status.ERROR
    log.message = result.message[:255]
    log.payload = {"fechas": len(rows)}
    log.save()
    if result.ok:
        Channel.objects.filter(pk=channel.pk).update(last_sync_at=timezone.now())
    else:
        from apps.comms.services import notify_role

        notify_role(
            channel.property,
            "manager",
            f"Error de sincronización con {channel}",
            log.message,
            url="/canales/",
            level="warning",
        )
    return log


def push_all(property_obj) -> list[SyncLog]:
    logs = [push_channel(c) for c in Channel.objects.filter(property=property_obj, is_active=True)]
    cache.delete(DIRTY_KEY.format(pk=property_obj.pk))
    return logs


def retry(log: SyncLog) -> SyncLog:
    """RF-CHA-04: reintento desde el panel de errores."""
    if log.direction != SyncLog.Direction.PUSH:
        raise ValidationError("Solo se reintentan envíos.")
    return _run_push(log)


@transaction.atomic
def receive_reservation(channel: Channel, payload: dict):
    """RF-CHA-02: reserva entrante (formato normalizado del channel manager).

    payload = {"external_id", "room_code", "rate_code", "arrival", "departure", "adults", "children",
               "guest": {"first_name", "last_name", "email", "phone", "country", "language"},
               "total" (opcional), "status": "new" | "cancelled"}
    """
    from apps.guests.models import Guest
    from apps.reservations import services as res
    from apps.reservations.models import Reservation

    log = SyncLog.objects.create(
        property=channel.property,
        channel=channel,
        direction=SyncLog.Direction.PULL,
        payload=payload,
        attempts=1,
    )
    existing = Reservation.objects.filter(
        property=channel.property, external_ref=payload["external_id"]
    ).first()
    try:
        if payload.get("status") == "cancelled":
            if existing is None:
                raise ValidationError("Cancelación de una reserva desconocida.")
            res.cancel_reservation(existing, f"Cancelada en {channel}", waive_penalty=False)
            log.status, log.message = SyncLog.Status.OK, f"Cancelada {existing.code}"
            log.save()
            mark_dirty(channel.property)
            return existing
        if existing is not None:
            log.status, log.message = SyncLog.Status.OK, f"Duplicada, ya existe {existing.code}"
            log.save()
            return existing
        mapping = (
            channel.room_mappings.select_related("room_type")
            .filter(external_code=payload["room_code"])
            .first()
        )
        rate_map = (
            channel.rate_mappings.select_related("rate_plan")
            .filter(external_code=payload.get("rate_code", ""))
            .first()
            or channel.rate_mappings.select_related("rate_plan").first()
        )
        if mapping is None or rate_map is None:
            raise ValidationError(f"Sin mapeo para la habitación {payload['room_code']}.")
        g = payload["guest"]
        guest = Guest.objects.filter(email__iexact=g.get("email", "")).first() if g.get("email") else None
        if guest is None:
            guest = Guest.objects.create(
                first_name=g["first_name"],
                last_name=g["last_name"],
                email=g.get("email", ""),
                phone=g.get("phone", ""),
                nationality=g.get("country", ""),
                residence_country=g.get("country", ""),
                language=g.get("language", "en"),
            )
        arrival = date.fromisoformat(payload["arrival"])
        departure = date.fromisoformat(payload["departure"])
        nights = (departure - arrival).days
        fixed = Decimal(str(payload["total"])) / nights if payload.get("total") and nights > 0 else None
        reservation = res.create_reservation(
            channel.property,
            res.ReservationData(
                guest=guest,
                room_type=mapping.room_type,
                rate_plan=rate_map.rate_plan,
                arrival=arrival,
                departure=departure,
                adults=int(payload.get("adults", 2)),
                children=int(payload.get("children", 0)),
                channel=channel.code if channel.code in dict(Reservation.Channel.choices) else "agency",
                status=Reservation.Status.GUARANTEED,
                guarantee=Reservation.Guarantee.CARD,
                external_ref=payload["external_id"],
                company=channel.company,
                notes=f"Comisión {channel.commission_percent}% · {channel}",
                fixed_nightly_rate=fixed.quantize(Decimal("0.01")) if fixed else None,
            ),
            allow_overbooking=False,
        )
        log.status, log.message = SyncLog.Status.OK, f"Creada {reservation.code}"
        log.save()
        audit.log(
            AuditLog.Action.CREATE,
            reservation,
            changes={"canal": channel.name, "externo": payload["external_id"]},
        )
        mark_dirty(channel.property)
        return reservation
    except ValidationError as exc:
        log.status = SyncLog.Status.ERROR
        log.message = " ".join(getattr(exc, "messages", [str(exc)]))[:255]
        log.save()
        from apps.comms.services import notify_role

        notify_role(
            channel.property,
            "manager",
            f"Reserva de {channel} no ingresó",
            log.message,
            url="/canales/",
            level="warning",
        )
        return None


def commission_report(property_obj, start, end):
    """RF-CHA-03: producción y comisión por canal."""
    from apps.reservations.models import Reservation

    rows = []
    for ch in Channel.objects.filter(property=property_obj):
        qs = Reservation.objects.filter(
            property=property_obj,
            channel=ch.code,
            arrival__gte=start,
            arrival__lt=end,
            status__in=Reservation.OCCUPYING_STATUSES,
        )
        revenue = sum((r.total_amount for r in qs), Decimal("0"))
        rows.append(
            {
                "channel": ch,
                "count": qs.count(),
                "revenue": revenue,
                "commission": (revenue * ch.commission_percent / 100).quantize(Decimal("0.01")),
            }
        )
    return rows
