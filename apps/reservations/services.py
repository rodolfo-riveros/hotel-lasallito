"""Reglas de negocio de reservas (RF-RES-01 a RF-RES-10, RNF-INT-01/02).

Todas las operaciones que tocan inventario corren dentro de una transacción y
bloquean las filas de los tipos de habitación de la propiedad
(`select_for_update`), de modo que dos recepcionistas no puedan vender la misma
habitación al mismo tiempo. En PostgreSQL además actúa la restricción de
exclusión de la base de datos.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog, Sequence
from apps.folio import services as folio_services
from apps.rates.services import quote
from apps.rooms.models import Room, RoomType

from .availability import free_rooms, room_is_free, type_availability
from .models import Reservation

AUDIT_FIELDS = [
    "status",
    "arrival",
    "departure",
    "room_type",
    "room",
    "rate_plan",
    "adults",
    "children",
    "total_amount",
    "discount_percent",
    "guest",
    "company",
]


@dataclass
class ReservationData:
    guest: object
    room_type: RoomType
    rate_plan: object
    arrival: date
    departure: date
    adults: int = 2
    children: int = 0
    extra_beds: int = 0
    cribs: int = 0
    room: Room | None = None
    channel: str = Reservation.Channel.DIRECT
    status: str = Reservation.Status.CONFIRMED
    company: object = None
    group: object = None
    discount_percent: Decimal = Decimal("0")
    discount_reason: str = ""
    promo_code: str = ""
    eta: object = None
    special_requests: str = ""
    notes: str = ""
    guarantee: str = Reservation.Guarantee.NONE
    deposit_required: Decimal = Decimal("0")
    pref_floor: int | None = None
    pref_view: str = ""
    pref_quiet: bool = False
    pref_accessible: bool = False
    external_ref: str = ""
    currency: str | None = None
    fixed_nightly_rate: Decimal | None = None  # tarifa pactada (grupos, canales)


def _lock_inventory(property_obj):
    list(RoomType.objects.select_for_update().filter(property=property_obj).values_list("pk", flat=True))


def next_code(property_obj) -> str:
    return f"LS{Sequence.next_value(property_obj, 'reservation'):06d}"


def _check_discount(user, property_obj, discount):
    """RF-TAR-07: descuento con tope por rol; arriba del tope requiere aprobar."""
    discount = Decimal(discount or 0)
    if discount <= 0 or user is None:
        return
    role = user.role_for(property_obj)
    limit = role.max_discount_percent if role else (Decimal("100") if user.is_superuser else Decimal("0"))
    if discount > limit and not user.has_pms_perm(property_obj, "rates.approve"):
        raise PermissionDenied(
            _("Su rol permite hasta %(l)s%% de descuento. Pida aprobación al gerente.") % {"l": limit}
        )


def _price(property_obj, data: ReservationData, exclude_pk=None):
    q = quote(
        data.rate_plan,
        data.room_type,
        data.arrival,
        data.departure,
        data.adults,
        data.children,
        data.extra_beds,
        data.cribs,
        currency=data.currency,
        discount_percent=data.discount_percent,
        promo_code=data.promo_code,
    )
    if data.fixed_nightly_rate is not None:
        for n in q.nights:
            n.amount = Decimal(data.fixed_nightly_rate)
        q.errors = [e for e in q.errors if "precio" not in e.lower()]
    return q


def _ensure_inventory(property_obj, data: ReservationData, user, exclude_pk=None, allow_overbooking=False):
    """Verifica disponibilidad por tipo y por habitación. Devuelve True si hubo sobreventa."""
    if data.status not in Reservation.ACTIVE_STATUSES:
        return False
    if data.room is not None:
        if data.room.room_type_id != data.room_type.pk:
            raise ValidationError(_("La habitación no corresponde al tipo elegido."))
        if not room_is_free(data.room, data.arrival, data.departure, exclude_pk=exclude_pk):
            raise ValidationError(
                _("La habitación %(n)s no está libre en esas fechas.") % {"n": data.room.number}
            )
    free = type_availability(
        property_obj, data.room_type, data.arrival, data.departure, exclude_pk=exclude_pk, group=data.group
    )
    if free > 0:
        return False
    # RF-RES-08: sobreventa controlada
    if allow_overbooking and user and user.has_pms_perm(property_obj, "reservations.approve"):
        if -free < property_obj.overbooking_limit:
            return True
    raise ValidationError(
        _("No hay disponibilidad de %(t)s para esas fechas. Puede registrarla en lista de espera.")
        % {"t": data.room_type}
    )


def _notify_overbooking(reservation, user):
    from apps.comms.services import notify_role

    notify_role(
        reservation.property,
        "manager",
        _("Sobreventa en %(t)s") % {"t": reservation.room_type},
        _("La reserva %(c)s se registró con sobreventa (%(a)s–%(d)s).")
        % {"c": reservation.code, "a": reservation.arrival, "d": reservation.departure},
        url=f"/reservas/{reservation.pk}/",
    )


@transaction.atomic
def create_reservation(
    property_obj, data: ReservationData, user=None, allow_overbooking=False
) -> Reservation:
    """RF-RES-01: crea la reserva, su folio principal y deja auditoría."""
    if data.guest.is_blacklisted and not (user and user.has_pms_perm(property_obj, "reservations.approve")):
        raise ValidationError(_("El huésped está en lista negra: %(r)s") % {"r": data.guest.blacklist_reason})
    _check_discount(user, property_obj, data.discount_percent)
    _lock_inventory(property_obj)
    q = _price(property_obj, data)
    if not q.ok and data.status != Reservation.Status.QUOTE:
        raise ValidationError(q.errors)
    overbooked = _ensure_inventory(property_obj, data, user, allow_overbooking=allow_overbooking)
    reservation = Reservation(
        property=property_obj,
        code=next_code(property_obj),
        status=data.status,
        channel=data.channel,
        external_ref=data.external_ref,
        guest=data.guest,
        company=data.company,
        group=data.group,
        room_type=data.room_type,
        room=data.room,
        arrival=data.arrival,
        departure=data.departure,
        eta=data.eta,
        adults=data.adults,
        children=data.children,
        extra_beds=data.extra_beds,
        cribs=data.cribs,
        rate_plan=data.rate_plan,
        currency=q.currency,
        nightly_rates=q.nightly_json() if q.nights else [],
        total_amount=q.total if q.nights else Decimal("0"),
        discount_percent=q.discount_percent,
        discount_reason=data.discount_reason,
        promo_code=q.promotion.code if q.promotion else "",
        special_requests=data.special_requests,
        notes=data.notes,
        guarantee=data.guarantee,
        deposit_required=data.deposit_required,
        pref_floor=data.pref_floor,
        pref_view=data.pref_view,
        pref_quiet=data.pref_quiet,
        pref_accessible=data.pref_accessible,
        overbooked=overbooked,
        language=data.guest.language,
    )
    try:
        with transaction.atomic():
            reservation.save()
    except IntegrityError as exc:
        raise ValidationError(_("La habitación acaba de ser ocupada por otra reserva.")) from exc
    if q.promotion:
        type(q.promotion).objects.filter(pk=q.promotion.pk).update(uses=q.promotion.uses + 1)
    folio_services.create_folio(
        property_obj,
        reservation=reservation,
        guest=data.guest,
        company=data.company,
        is_main=True,
    )
    audit.log(
        AuditLog.Action.CREATE,
        reservation,
        changes={"total": str(reservation.total_amount), "canal": reservation.channel},
        user=user,
    )
    if reservation.discount_percent:
        audit.log(
            AuditLog.Action.DISCOUNT,
            reservation,
            changes={"descuento_%": str(reservation.discount_percent)},
            reason=reservation.discount_reason,
            user=user,
        )
    if overbooked:
        _notify_overbooking(reservation, user)
    if reservation.status in (Reservation.Status.CONFIRMED, Reservation.Status.GUARANTEED):
        transaction.on_commit(lambda: _send_confirmation(reservation.pk))
    return reservation


def _send_confirmation(pk):
    from apps.comms.services import send_event

    try:
        send_event("confirmation", Reservation.objects.get(pk=pk))
    except Exception:  # noqa: BLE001 - un fallo de correo no anula la reserva
        import logging

        logging.getLogger(__name__).exception("No se pudo enviar la confirmación %s", pk)


@transaction.atomic
def update_reservation(
    reservation: Reservation, data: ReservationData, user=None, reprice=True
) -> Reservation:
    """RF-RES-10: modifica y deja historial con valor anterior y nuevo."""
    if reservation.status in (
        Reservation.Status.CHECKED_OUT,
        Reservation.Status.CANCELLED,
        Reservation.Status.NO_SHOW,
    ):
        raise ValidationError(_("La reserva ya está cerrada."))
    _check_discount(user, reservation.property, data.discount_percent)
    _lock_inventory(reservation.property)
    before = audit.snapshot(reservation, AUDIT_FIELDS)
    _ensure_inventory(reservation.property, data, user, exclude_pk=reservation.pk)
    if reservation.status == Reservation.Status.CHECKED_IN and data.arrival != reservation.arrival:
        raise ValidationError(_("No se puede cambiar la llegada de un huésped que ya ingresó."))
    for attr in [
        "guest",
        "room_type",
        "room",
        "rate_plan",
        "arrival",
        "departure",
        "adults",
        "children",
        "extra_beds",
        "cribs",
        "company",
        "eta",
        "special_requests",
        "notes",
        "guarantee",
        "deposit_required",
        "discount_reason",
        "pref_floor",
        "pref_view",
        "pref_quiet",
        "pref_accessible",
    ]:
        setattr(reservation, attr, getattr(data, attr))
    if data.status and reservation.status not in (Reservation.Status.CHECKED_IN,):
        reservation.status = data.status
    if reprice:
        q = _price(reservation.property, data, exclude_pk=reservation.pk)
        if not q.ok:
            raise ValidationError(q.errors)
        reservation.nightly_rates = q.nightly_json()
        reservation.total_amount = q.total
        reservation.discount_percent = q.discount_percent
        reservation.currency = q.currency
    try:
        with transaction.atomic():
            reservation.save()
    except IntegrityError as exc:
        raise ValidationError(_("La habitación acaba de ser ocupada por otra reserva.")) from exc
    log = audit.log_changes(reservation, before)
    if log and "rate_plan" in log.changes or log and "total_amount" in log.changes:
        audit.log(AuditLog.Action.RATE_CHANGE, reservation, changes=log.changes, user=user)
    return reservation


def data_from(reservation: Reservation, **overrides) -> ReservationData:
    fields = ReservationData.__dataclass_fields__
    values = {f: getattr(reservation, f) for f in fields if hasattr(reservation, f)}
    values["fixed_nightly_rate"] = None
    values.update(overrides)
    return ReservationData(**{k: v for k, v in values.items() if k in fields})


@transaction.atomic
def move_reservation(
    reservation: Reservation, *, room=None, arrival=None, departure=None, user=None
) -> Reservation:
    """RF-RES-02: mover o extender desde el calendario (arrastrar y soltar)."""
    room = room or reservation.room
    room_type = room.room_type if room else reservation.room_type
    arrival = arrival or reservation.arrival
    departure = departure or reservation.departure
    reprice = (arrival, departure, room_type.pk) != (
        reservation.arrival,
        reservation.departure,
        reservation.room_type_id,
    )
    data = data_from(reservation, room=room, room_type=room_type, arrival=arrival, departure=departure)
    return update_reservation(reservation, data, user=user, reprice=reprice)


@transaction.atomic
def assign_room(reservation: Reservation, room: Room, user=None) -> Reservation:
    """RF-RES-09: asignación manual."""
    if room.property_id != reservation.property_id:
        raise ValidationError(_("Habitación de otra propiedad."))
    return move_reservation(reservation, room=room, user=user)


def best_room(reservation: Reservation):
    """RF-RES-09: habitación libre que mejor cumple las preferencias."""
    candidates = list(
        free_rooms(
            reservation.property,
            reservation.arrival,
            reservation.departure,
            room_type=reservation.room_type,
            exclude_pk=reservation.pk,
        )
    )
    if not candidates:
        return None

    def score(room):
        s = 0
        if reservation.pref_floor is not None and room.floor == reservation.pref_floor:
            s += 4
        if reservation.pref_view and room.view == reservation.pref_view:
            s += 3
        if reservation.pref_quiet and room.is_quiet:
            s += 2
        if reservation.pref_accessible:
            s += 10 if room.is_accessible else -10
        if room.is_ready:
            s += 1
        return (-s, room.floor, room.sort_order, room.number)

    return sorted(candidates, key=score)[0]


@transaction.atomic
def auto_assign(reservation: Reservation, user=None):
    room = best_room(reservation)
    if room is None:
        raise ValidationError(_("No hay habitaciones libres de ese tipo."))
    return assign_room(reservation, room, user)


@transaction.atomic
def cancel_reservation(reservation: Reservation, reason: str, user=None, waive_penalty=False) -> Reservation:
    """RF-RES-06: cancelación con cálculo automático de la penalidad."""
    if reservation.status not in Reservation.PRE_ARRIVAL_STATUSES + ("quote", "waitlist"):
        raise ValidationError(_("Solo se pueden cancelar reservas que aún no ingresan."))
    if not reason:
        raise ValidationError(_("Indique el motivo de la cancelación."))
    penalty = Decimal("0")
    if reservation.status in Reservation.PRE_ARRIVAL_STATUSES:
        policy = reservation.rate_plan.cancellation_policy
        penalty = policy.cancellation_penalty(
            reservation.arrival,
            reservation.property.current_business_date(),
            reservation.nightly_amounts(),
            reservation.total_amount,
        )
    if waive_penalty and penalty:
        if not (user and user.has_pms_perm(reservation.property, "reservations.approve")):
            raise PermissionDenied(_("Solo el gerente puede condonar la penalidad."))
        penalty = Decimal("0")
    before = audit.snapshot(reservation, ["status"])
    reservation.status = Reservation.Status.CANCELLED
    reservation.cancelled_at = timezone.now()
    reservation.cancellation_reason = reason
    reservation.cancellation_penalty = penalty
    reservation.save()
    if penalty > 0:
        folio = folio_services.main_folio(reservation)
        folio_services.post_charge(
            folio,
            folio_services.get_concept(reservation.property, "penalty"),
            penalty,
            description=_("Penalidad por cancelación %(c)s") % {"c": reservation.code},
            source="penalty",
            user=user,
        )
    audit.log(
        AuditLog.Action.VOID,
        reservation,
        changes={**{k: [before[k], reservation.status] for k in before}, "penalidad": str(penalty)},
        reason=reason,
        user=user,
    )
    transaction.on_commit(lambda: _send_event_safe("cancellation", reservation.pk))
    return reservation


def _send_event_safe(event, pk):
    from apps.comms.services import send_event

    try:
        send_event(event, Reservation.objects.get(pk=pk))
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("No se pudo enviar %s %s", event, pk)


@transaction.atomic
def mark_no_show(reservation: Reservation, user=None) -> Reservation:
    """No show: libera la habitación y cobra según la política (garantizadas)."""
    if reservation.status not in Reservation.PRE_ARRIVAL_STATUSES:
        raise ValidationError(_("La reserva no está pendiente de llegada."))
    charge = Decimal("0")
    if (
        reservation.status == Reservation.Status.GUARANTEED
        or reservation.rate_plan.cancellation_policy.is_non_refundable
    ):
        charge = reservation.rate_plan.cancellation_policy.no_show_charge(
            reservation.nightly_amounts(), reservation.total_amount
        )
    reservation.status = Reservation.Status.NO_SHOW
    reservation.cancellation_penalty = charge
    reservation.save()
    if charge > 0:
        folio_services.post_charge(
            folio_services.main_folio(reservation),
            folio_services.get_concept(reservation.property, "penalty"),
            charge,
            description=_("No show %(c)s") % {"c": reservation.code},
            source="penalty",
        )
    audit.log(
        AuditLog.Action.UPDATE, reservation, changes={"status": ["no_show"], "cargo": str(charge)}, user=user
    )
    return reservation


@transaction.atomic
def confirm_waitlist(reservation: Reservation, user=None) -> Reservation:
    data = data_from(reservation, status=Reservation.Status.CONFIRMED)
    return update_reservation(reservation, data, user=user)


def history(reservation: Reservation):
    """RF-RES-10: historial completo de cambios."""
    return AuditLog.objects.filter(
        object_type="reservations.Reservation", object_id=str(reservation.pk)
    ).select_related("user")
