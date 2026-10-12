"""Check-in, check-out, walk-in, cambios de habitación y cierre de día (RF-REC-02 a RF-REC-13)."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog, Sequence
from apps.folio import services as folio_services
from apps.folio.models import Charge, Folio
from apps.reservations import services as res_services
from apps.reservations.availability import room_is_free
from apps.reservations.models import Reservation
from apps.rooms.models import Room

from .models import LuggageTicket, NightAudit, RegistrationCard, RoomMove


def _now_local():
    return timezone.localtime()


def _fee(reservation, percent) -> Decimal:
    first = reservation.nightly_amounts()[0] if reservation.nightly_rates else Decimal("0")
    return folio_services.q2(first * Decimal(percent) / 100)


@transaction.atomic
def check_in(
    reservation: Reservation,
    *,
    user,
    room: Room | None = None,
    card_data: dict | None = None,
    signature: str = "",
    document_verified: bool = False,
    validate_non_domiciled: bool = False,
    charge_early: bool | None = None,
    allow_dirty: bool = False,
) -> Reservation:
    """RF-REC-02: buscar reserva, validar documento, asignar habitación, firmar ficha."""
    property_obj = reservation.property
    today = property_obj.current_business_date()
    if reservation.status not in Reservation.PRE_ARRIVAL_STATUSES:
        raise ValidationError(_("La reserva no está pendiente de llegada."))
    if reservation.arrival > today:
        raise ValidationError(
            _("La reserva llega el %(d)s.") % {"d": reservation.arrival.strftime("%d/%m/%Y")}
        )
    if reservation.guest.is_blacklisted:
        raise ValidationError(_("Huésped en lista negra: %(r)s") % {"r": reservation.guest.blacklist_reason})
    if not reservation.guest.doc_number:
        raise ValidationError(_("Registre el documento del huésped antes del check-in."))
    room = room or reservation.room
    if room is None:
        room = res_services.best_room(reservation)
        if room is None:
            raise ValidationError(_("No hay habitaciones libres de ese tipo."))
    if room.pk != reservation.room_id:
        if not room_is_free(room, reservation.arrival, reservation.departure, exclude_pk=reservation.pk):
            raise ValidationError(_("La habitación %(n)s no está libre.") % {"n": room.number})
        res_services.assign_room(reservation, room, user)
        reservation.refresh_from_db()
    if not room.is_ready and not allow_dirty:
        raise ValidationError(_("La habitación %(n)s aún no está limpia.") % {"n": room.number})

    # RF-TAR-06 / RF-FAC-04: exoneración de IGV a no domiciliados con rastro
    if validate_non_domiciled:
        guest = reservation.guest
        if not guest.is_non_domiciled:
            raise ValidationError(
                _("Para exonerar el IGV el huésped debe ser extranjero no domiciliado con pasaporte.")
            )
        if not guest.peru_entry_date:
            raise ValidationError(_("Registre la fecha de ingreso al Perú (TAM) para exonerar el IGV."))
        if not reservation.igv_exempt:
            reservation.igv_exempt = True
            audit.log(
                AuditLog.Action.APPROVE,
                reservation,
                changes={
                    "igv_exempt": [False, True],
                    "pasaporte": guest.masked_doc,
                    "ingreso_peru": guest.peru_entry_date.isoformat(),
                },
                reason=_("Exoneración de IGV a no domiciliado"),
                user=user,
            )

    RegistrationCard.objects.update_or_create(
        reservation=reservation,
        defaults={
            "data": card_data or {},
            "signature": signature,
            "signed_at": timezone.now() if signature else None,
            "document_verified": document_verified,
            "terms_accepted": bool(signature),
        },
    )
    reservation.status = Reservation.Status.CHECKED_IN
    reservation.checked_in_at = timezone.now()
    reservation.save()
    folio_services.main_folio(reservation)

    # RF-REC-07: early check-in con cargo configurable
    if charge_early is None:
        charge_early = _now_local().time() < property_obj.check_in_time and reservation.arrival == today
    if charge_early and property_obj.early_checkin_fee_percent > 0:
        folio_services.post_charge(
            reservation.main_folio,
            folio_services.get_concept(property_obj, "early_checkin"),
            _fee(reservation, property_obj.early_checkin_fee_percent),
            description=_("Early check-in"),
            source=Charge.Source.EARLY_CHECKIN,
        )
    audit.log(
        AuditLog.Action.UPDATE,
        reservation,
        changes={"status": ["checked_in"], "habitación": room.number},
        user=user,
    )
    transaction.on_commit(lambda: res_services._send_event_safe("welcome", reservation.pk))
    return reservation


@transaction.atomic
def move_room(reservation: Reservation, new_room: Room, *, kind: str, reason: str, user, keep_rate=True):
    """RF-REC-08: cambio de habitación conservando el folio."""
    if reservation.status not in Reservation.ACTIVE_STATUSES or reservation.room is None:
        raise ValidationError(_("La reserva no tiene habitación asignada."))
    if not reason:
        raise ValidationError(_("Indique el motivo."))
    old_room = reservation.room
    res_services.update_reservation(
        reservation,
        res_services.data_from(reservation, room=new_room, room_type=new_room.room_type),
        user=user,
        reprice=not keep_rate,
    )
    RoomMove.objects.create(
        reservation=reservation,
        from_room=old_room,
        to_room=new_room,
        kind=kind,
        reason=reason,
        keep_rate=keep_rate,
    )
    if reservation.status == Reservation.Status.CHECKED_IN:
        old_room.hk_status = Room.HKStatus.DIRTY
        old_room.save(update_fields=["hk_status"])
    return reservation


@transaction.atomic
def check_out(
    reservation: Reservation, *, user, charge_late: bool = False, force_balance=False
) -> Reservation:
    """RF-REC-10: check-out con folio final saldado."""
    if reservation.status != Reservation.Status.CHECKED_IN:
        raise ValidationError(_("La reserva no está en casa."))
    property_obj = reservation.property
    today = property_obj.current_business_date()
    if charge_late and property_obj.late_checkout_fee_percent > 0:
        folio_services.post_charge(
            reservation.main_folio,
            folio_services.get_concept(property_obj, "late_checkout"),
            _fee(reservation, property_obj.late_checkout_fee_percent),
            description=_("Late check-out"),
            source=Charge.Source.LATE_CHECKOUT,
        )
    balance = reservation.balance
    if balance != 0 and not force_balance:
        raise ValidationError(
            _("El folio tiene saldo de S/ %(b)s. Cobre o transfiera antes de salir.") % {"b": balance}
        )
    if force_balance and not user.has_pms_perm(property_obj, "folio.approve"):
        raise PermissionDenied(_("Solo un supervisor puede dar salida con saldo."))
    if reservation.departure > today:
        # Salida anticipada: libera las noches no usadas.
        reservation.departure = max(today, reservation.arrival + timedelta(days=1))
        reservation.nightly_rates = [
            n for n in reservation.nightly_rates if n["date"] < reservation.departure.isoformat()
        ]
        reservation.total_amount = sum(
            (Decimal(n["amount"]) for n in reservation.nightly_rates), Decimal("0")
        )
    reservation.status = Reservation.Status.CHECKED_OUT
    reservation.checked_out_at = timezone.now()
    reservation.save()
    for folio in reservation.folios.filter(status=Folio.Status.OPEN):
        if folio.balance == 0:
            folio_services.close_folio(folio, user)
    room = reservation.room
    if room:
        room.hk_status = Room.HKStatus.DIRTY
        room.save(update_fields=["hk_status"])
        from apps.housekeeping.services import create_departure_task

        create_departure_task(room, today)
    guest = reservation.guest
    spent = (
        Charge.objects.filter(folio__reservation=reservation, is_void=False).aggregate(s=Sum("amount"))["s"]
        or 0
    )
    guest.total_stays += 1
    guest.total_nights += reservation.nights
    guest.total_spent += spent
    if guest.total_stays >= 2 and "recurrent" not in (guest.tags or []):
        guest.tags = [*(guest.tags or []), "recurrent"]
    guest.save()
    try:
        from apps.guests.loyalty import award_stay_points

        award_stay_points(reservation, spent)
    except ImportError:
        pass
    audit.log(
        AuditLog.Action.UPDATE,
        reservation,
        changes={"status": ["checked_out"], "consumo": str(spent)},
        user=user,
    )
    transaction.on_commit(lambda: res_services._send_event_safe("thanks", reservation.pk))
    return reservation


@transaction.atomic
def walk_in(property_obj, *, guest, room: Room, rate_plan, nights: int, adults=2, children=0, user, **card):
    """RF-REC-06: walk-in en un solo paso: reserva + asignación + check-in."""
    today = property_obj.current_business_date()
    data = res_services.ReservationData(
        guest=guest,
        room_type=room.room_type,
        rate_plan=rate_plan,
        arrival=today,
        departure=today + timedelta(days=nights),
        adults=adults,
        children=children,
        room=room,
        channel=Reservation.Channel.WALK_IN,
    )
    reservation = res_services.create_reservation(property_obj, data, user=user)
    return check_in(reservation, user=user, room=room, charge_early=False, **card)


def new_luggage_ticket(property_obj, **fields) -> LuggageTicket:
    number = f"EQ{Sequence.next_value(property_obj, 'luggage'):05d}"
    return LuggageTicket.objects.create(property=property_obj, number=number, **fields)


# --------------------------------------------------------------------------
# Cierre de día (night audit)
# --------------------------------------------------------------------------


@transaction.atomic
def run_night_audit(property_obj, *, user) -> NightAudit:
    """RF-REC-13: cargo de habitaciones, no shows, control de caja y avance de fecha."""
    if not user.has_pms_perm(property_obj, "frontdesk.approve"):
        raise PermissionDenied(_("Solo el jefe de recepción o el night auditor cierran el día."))
    from apps.core.models import Property

    property_obj = Property.objects.select_for_update().get(pk=property_obj.pk)
    day = property_obj.current_business_date()
    if NightAudit.objects.filter(property=property_obj, business_date=day).exists():
        raise ValidationError(_("El día %(d)s ya fue cerrado.") % {"d": day.strftime("%d/%m/%Y")})
    warnings = []
    lodging = folio_services.get_concept(property_obj, "lodging")

    posted, revenue = 0, Decimal("0")
    in_house = Reservation.objects.filter(
        property=property_obj, status=Reservation.Status.CHECKED_IN, arrival__lte=day, departure__gt=day
    ).select_related("room", "guest")
    for r in in_house:
        folio = folio_services.main_folio(r)
        if Charge.objects.filter(
            folio__reservation=r, source=Charge.Source.NIGHT_AUDIT, service_date=day, is_void=False
        ).exists():
            continue
        amount = r.rate_for(day)
        if r.currency == "USD":
            from apps.core.models import ExchangeRate

            fx = ExchangeRate.for_date("USD", day)
            amount = folio_services.q2(amount * (fx.sell if fx else Decimal("1")))
        folio_services.post_charge(
            folio,
            lodging,
            amount,
            description=_("Alojamiento hab. %(n)s") % {"n": r.room.number if r.room else "-"},
            service_date=day,
            source=Charge.Source.NIGHT_AUDIT,
            reference=r.code,
        )
        posted += 1
        revenue += amount

    no_shows = []
    for r in Reservation.objects.filter(
        property=property_obj, arrival=day, status__in=Reservation.PRE_ARRIVAL_STATUSES
    ):
        res_services.mark_no_show(r, user=user)
        no_shows.append(r.code)

    overdue = Reservation.objects.filter(
        property=property_obj, status=Reservation.Status.CHECKED_IN, departure__lte=day
    ).count()
    if overdue:
        warnings.append(_("%(n)s huéspedes debieron salir hoy y siguen en casa.") % {"n": overdue})
    from apps.folio.models import CashSession

    open_sessions = CashSession.objects.filter(property=property_obj, status=CashSession.Status.OPEN)
    if open_sessions.exists():
        warnings.append(
            _("Cajas abiertas: %(c)s")
            % {"c": ", ".join(str(s.user) for s in open_sessions.select_related("user"))}
        )
    from apps.rooms.models import Room as RoomModel

    total_rooms = RoomModel.objects.filter(property=property_obj, is_active=True).count()
    summary = {
        "habitaciones_cargadas": posted,
        "ingreso_alojamiento": str(revenue),
        "no_shows": no_shows,
        "ocupacion_%": round(posted * 100 / total_rooms, 1) if total_rooms else 0,
        "adr": str(folio_services.q2(revenue / posted)) if posted else "0",
    }
    audit_record = NightAudit.objects.create(
        property=property_obj, business_date=day, summary=summary, warnings=[str(w) for w in warnings]
    )
    property_obj.business_date = day + timedelta(days=1)
    property_obj.save(update_fields=["business_date"])
    audit.log(
        AuditLog.Action.APPROVE,
        audit_record,
        changes=summary,
        reason=_("Cierre de día"),
        user=user,
        property=property_obj,
    )
    from apps.housekeeping.services import generate_daily_tasks

    generate_daily_tasks(property_obj, property_obj.business_date)
    return audit_record


def wakeups_due(property_obj, minutes=30):
    from .models import WakeUpCall

    now = timezone.now()
    return WakeUpCall.objects.filter(
        property=property_obj, done=False, scheduled_for__lte=now + timedelta(minutes=minutes)
    ).select_related("reservation__room", "reservation__guest")


def combine(day, time_value):
    return timezone.make_aware(datetime.combine(day, time_value))
