"""Escenarios de práctica con guía paso a paso (RF-SIM-03).

Cada escenario prepara el hotel (``setup``) y define pasos que el sistema verifica
solo, mirando lo que el alumno hizo en su propiedad desde que se lanzó.
"""

from dataclasses import dataclass, field
from datetime import time, timedelta

from django.utils.translation import gettext_lazy as _


@dataclass
class Step:
    text: str
    hint: str
    check: object  # callable(run) -> bool


@dataclass
class Scenario:
    code: str
    title: str
    summary: str
    setup: object = None  # callable(run, user) -> dict
    steps: list[Step] = field(default_factory=list)


# -- utilidades --------------------------------------------------------------


def _practice_guest(first, last, n):
    from apps.guests.models import Guest

    email = f"practica{n}@aula.example"
    guest = Guest.objects.filter(email=email).first()
    return guest or Guest.objects.create(
        first_name=first,
        last_name=last,
        email=email,
        nationality="US",
        residence_country="US",
        language="en",
        doc_type="7",
        doc_number=f"AULA{n:05d}",
    )


def _plan(prop):
    from apps.rates.models import RatePlan

    return (
        RatePlan.objects.filter(property=prop, is_active=True, code="rack-bb").first()
        or RatePlan.objects.filter(property=prop, is_active=True).first()
    )


def _reservations(run):
    from apps.reservations.models import Reservation

    return Reservation.objects.filter(pk__in=run.data.get("reservations", []))


# -- 1. Grupo con llegada tardía ---------------------------------------------


def setup_late_group(run, user):
    from apps.reservations import services as res
    from apps.reservations.availability import free_rooms
    from apps.reservations.models import GroupBlock

    prop = run.property
    today = prop.current_business_date()
    plan = _plan(prop)
    group = GroupBlock.objects.create(
        property=prop,
        code=f"G{run.pk:04d}",
        name="Andes Explorer Tours (práctica)",
        contact_name="Mark Lee",
        arrival=today,
        departure=today + timedelta(days=2),
        release_date=today,
        rate_plan=plan,
        status=GroupBlock.Status.DEFINITE,
    )
    pks = []
    rooms = list(free_rooms(prop, today, today + timedelta(days=2)))[:3]
    for i, room in enumerate(rooms):
        guest = _practice_guest(["Mark", "Anna", "Peter"][i], ["Lee", "Brown", "Clark"][i], 100 + i)
        r = res.create_reservation(
            prop,
            res.ReservationData(
                guest=guest,
                room_type=room.room_type,
                rate_plan=plan,
                arrival=today,
                departure=today + timedelta(days=2),
                group=group,
                eta=time(23, 30),
                special_requests="Llegan en el último tren desde Aguas Calientes",
                fixed_nightly_rate=None,
            ),
            user=user,
        )
        pks.append(r.pk)
    return {"reservations": pks, "group": group.pk}


def _all_assigned(run):
    qs = _reservations(run)
    return qs.exists() and not qs.filter(room__isnull=True).exists()


def _all_checked_in(run):
    qs = _reservations(run)
    return qs.exists() and not qs.exclude(status="checked_in").exists()


def _late_charge(run):
    from apps.folio.models import Charge

    return (
        Charge.objects.filter(
            folio__reservation__in=_reservations(run), created_at__gte=run.created_at, is_void=False
        )
        .exclude(concept__category="lodging")
        .exists()
    )


# -- 2. Overbooking ----------------------------------------------------------


def setup_overbooking(run, user):
    from apps.reservations import services as res
    from apps.reservations.availability import availability_grid
    from apps.rooms.models import RoomType

    prop = run.property
    today = prop.current_business_date()
    tomorrow = today + timedelta(days=1)
    plan = _plan(prop)
    grid = availability_grid(prop, today, tomorrow)
    types = sorted(
        RoomType.objects.filter(property=prop, is_active=True), key=lambda t: grid.get(t.pk, {}).get(today, 0)
    )
    room_type = next((t for t in types if grid.get(t.pk, {}).get(today, 0) >= 0), types[0])
    free = max(0, grid.get(room_type.pk, {}).get(today, 0))
    fillers = []
    for i in range(free):
        r = res.create_reservation(
            prop,
            res.ReservationData(
                guest=_practice_guest("Relleno", f"Práctica {i + 1}", 200 + i),
                room_type=room_type,
                rate_plan=plan,
                arrival=today,
                departure=tomorrow,
            ),
            user=user,
        )
        fillers.append(r.pk)
    if prop.overbooking_limit < 1:
        prop.overbooking_limit = 1
        prop.save(update_fields=["overbooking_limit"])
    over = res.create_reservation(
        prop,
        res.ReservationData(
            guest=_practice_guest("Laura", "Gómez", 299),
            room_type=room_type,
            rate_plan=plan,
            arrival=today,
            departure=tomorrow,
            special_requests="Llega a las 20:00",
        ),
        user=user,
        allow_overbooking=True,
    )
    return {"reservations": [over.pk], "fillers": fillers, "room_type": room_type.name}


def _overbooking_solved(run):
    r = _reservations(run).first()
    return bool(r) and (r.status == "cancelled" or r.room_id is not None)


def _guest_contacted(run):
    from apps.comms.models import Message

    return Message.objects.filter(reservation__in=_reservations(run), created_at__gte=run.created_at).exists()


# -- 3. Cambio de habitación -------------------------------------------------


def setup_room_change(run, user):
    from apps.reservations.models import Reservation

    r = (
        Reservation.objects.filter(property=run.property, status="checked_in", room__isnull=False)
        .select_related("room")
        .order_by("pk")
        .first()
    )
    if r is None:
        return {"error": str(_("No hay huéspedes en casa: haga un check-in antes de lanzar este escenario."))}
    return {
        "reservations": [r.pk],
        "room": r.room_id,
        "room_number": r.room.number,
        "story": f"El huésped de la habitación {r.room.number} reclama que la ducha no tiene agua caliente.",
    }


def _work_order(run):
    from apps.maintenance.models import WorkOrder

    return WorkOrder.objects.filter(
        property=run.property, room_id=run.data.get("room"), created_at__gte=run.created_at
    ).exists()


def _moved(run):
    r = _reservations(run).first()
    return bool(r) and r.room_id not in (None, run.data.get("room"))


# -- 4. Nota de crédito ------------------------------------------------------


def _invoice_issued(run):
    from apps.billing.models import Invoice

    return Invoice.objects.filter(
        property=run.property, doc_type__in=["01", "03"], created_at__gte=run.created_at
    ).exists()


def _credit_note(run):
    from apps.billing.models import Invoice

    return Invoice.objects.filter(
        property=run.property, doc_type="07", created_at__gte=run.created_at
    ).exists()


# -- 5. Cierre de caja con diferencia ----------------------------------------


def _cash_opened(run):
    from apps.folio.models import CashSession

    return CashSession.objects.filter(property=run.property, created_at__gte=run.created_at).exists()


def _cash_payment(run):
    from apps.folio.models import Payment

    return Payment.objects.filter(
        folio__property=run.property, method__in=["cash_pen", "cash_usd"], created_at__gte=run.created_at
    ).exists()


def _cash_closed_with_difference(run):
    from apps.folio.models import CashSession

    return (
        CashSession.objects.filter(property=run.property, created_at__gte=run.created_at, status="closed")
        .exclude(difference=0)
        .exclude(notes="")
        .exists()
    )


SCENARIOS = {
    s.code: s
    for s in [
        Scenario(
            "late_group",
            _("Grupo de turistas con llegada tardía"),
            _("Tres habitaciones de una agencia llegan a las 23:30 en el último tren."),
            setup_late_group,
            [
                Step(
                    _("Asigne habitación a las tres reservas del grupo"),
                    _("Reservas → filtre por grupo → Asignar, o use la asignación automática."),
                    _all_assigned,
                ),
                Step(
                    _("Haga el check-in de los tres huéspedes"),
                    _("Recepción → Llegadas. Registre documento y firma de cada uno."),
                    _all_checked_in,
                ),
                Step(
                    _("Cargue la cena fría o el box lunch al folio de alguno"),
                    _("Folio → Agregar cargo (restaurante) o venda desde el restaurante a la habitación."),
                    _late_charge,
                ),
            ],
        ),
        Scenario(
            "overbooking",
            _("Overbooking"),
            _("Se vendió una habitación más de las que hay. Reubique al huésped y avísele."),
            setup_overbooking,
            [
                Step(
                    _("Resuelva la reserva sobrevendida: asígnele otra habitación (upgrade) o reubíquela"),
                    _("Abra la reserva marcada con overbooking y cambie el tipo o asígnele una habitación."),
                    _overbooking_solved,
                ),
                Step(
                    _("Envíe un mensaje al huésped explicando la solución"),
                    _("En la reserva, use Comunicaciones → enviar correo o WhatsApp."),
                    _guest_contacted,
                ),
            ],
        ),
        Scenario(
            "room_change",
            _("Cambio de habitación"),
            _("Un huésped en casa reclama por un desperfecto en su habitación."),
            setup_room_change,
            [
                Step(
                    _("Registre la orden de trabajo de la habitación con el problema"),
                    _("Mantenimiento → Nueva orden, con la habitación indicada."),
                    _work_order,
                ),
                Step(
                    _("Cambie al huésped de habitación conservando su folio"),
                    _("Recepción → En casa → Cambiar habitación (motivo: mantenimiento)."),
                    _moved,
                ),
            ],
        ),
        Scenario(
            "credit_note",
            _("Nota de crédito"),
            _("Se emitió un comprobante con un error y hay que corregirlo."),
            None,
            [
                Step(
                    _("Emita una boleta o factura desde un folio"),
                    _("Folio → Emitir comprobante."),
                    _invoice_issued,
                ),
                Step(
                    _("Emita la nota de crédito que la corrige"),
                    _("Facturación → abra el comprobante → Nota de crédito (motivo 01 o 07)."),
                    _credit_note,
                ),
            ],
        ),
        Scenario(
            "cash_difference",
            _("Cierre de caja con diferencia"),
            _("Al contar el efectivo no cuadra. Cierre la caja y justifique la diferencia."),
            None,
            [
                Step(_("Abra su caja con fondo inicial"), _("Folios y caja → Abrir caja."), _cash_opened),
                Step(
                    _("Cobre en efectivo algún folio"),
                    _("Folio → Registrar pago en efectivo."),
                    _cash_payment,
                ),
                Step(
                    _("Cierre la caja con un conteo distinto al esperado y explique la diferencia"),
                    _("Folios y caja → Cerrar caja: escriba el conteo real y la observación."),
                    _cash_closed_with_difference,
                ),
            ],
        ),
    ]
}


def progress(run) -> list[tuple[Step, bool]]:
    scenario = SCENARIOS.get(run.scenario)
    if scenario is None or run.data.get("error"):
        return []
    return [(step, bool(step.check(run))) for step in scenario.steps]
