"""Modo aula: hoteles de práctica, eventos del docente y avance (RF-SIM-01 a 05)."""

import random
import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.cache import bump_version
from apps.core import audit
from apps.core.models import AuditLog, Property

from .models import PracticeEvent, ScenarioRun
from .scenarios import SCENARIOS, progress

COPY_FIELDS = [
    "legal_name",
    "ruc",
    "kind",
    "category_stars",
    "address",
    "district",
    "city",
    "province",
    "region",
    "ubigeo",
    "phone",
    "email",
    "time_zone",
    "base_currency_id",
    "check_in_time",
    "check_out_time",
]


# -- Hoteles de práctica (RF-SIM-01/02) --------------------------------------


def load_sample_data(prop, user=None):
    """Carga el hotel de ejemplo completo en la propiedad (lo mismo que `seed_pms --demo`)."""
    from apps.core.demo import load_bookings, load_operations, load_phase2, load_phase3

    _types, _rack, guests = load_operations(prop)
    load_bookings(prop, user, guests)
    load_phase2(prop)
    load_phase3(prop)


def _copy_taxes(template, prop):
    from apps.core.models import TaxRule

    for t in TaxRule.objects.filter(property=template):
        TaxRule.objects.get_or_create(
            property=prop,
            code=t.code,
            defaults={
                f.name: getattr(t, f.name)
                for f in TaxRule._meta.fields
                if f.name not in ("id", "property", "code")
            },
        )


@transaction.atomic
def create_practice_property(name, code, *, template: Property, user=None) -> Property:
    """RF-SIM-02: hotel aislado para un alumno o grupo. El docente lo ve junto a los demás."""
    from apps.accounts.models import PropertyAccess, Role

    if Property.objects.filter(code=code).exists():
        raise ValidationError(_("Ya existe una propiedad con el código %(c)s.") % {"c": code})
    prop = Property.objects.create(
        name=name,
        code=code,
        **{f: getattr(template, f) for f in COPY_FIELDS},
        business_date=template.current_business_date(),
    )
    _copy_taxes(template, prop)
    teacher = Role.objects.filter(code="teacher").first()
    if teacher is not None:
        for access in PropertyAccess.objects.filter(property=template, role=teacher, is_active=True):
            PropertyAccess.objects.get_or_create(user=access.user, property=prop, defaults={"role": teacher})
    if user is not None and teacher is not None:
        PropertyAccess.objects.get_or_create(user=user, property=prop, defaults={"role": teacher})
    audit.log(AuditLog.Action.CREATE, prop, changes={"aula": "hotel de práctica"}, user=user, property=prop)
    return prop


@transaction.atomic
def archive_and_clone(prop: Property, user=None) -> Property:
    """RF-SIM-01: "restablecer" archiva el hotel con todo lo que hicieron los alumnos y crea uno limpio igual."""
    from apps.accounts.models import PropertyAccess

    stamp = timezone.now().strftime("%Y%m%d%H%M")
    name, code = prop.name, prop.code
    Property.objects.filter(pk=prop.pk).update(
        code=f"{code[:15]}-arch-{stamp}", name=f"{name} (archivado {stamp})", is_active=False
    )
    fresh = Property.objects.create(
        name=name, code=code, **{f: getattr(prop, f) for f in COPY_FIELDS}, business_date=timezone.localdate()
    )
    _copy_taxes(prop, fresh)
    for access in PropertyAccess.objects.filter(property=prop):
        PropertyAccess.objects.get_or_create(
            user=access.user, property=fresh, defaults={"role": access.role, "is_active": access.is_active}
        )
    PropertyAccess.objects.filter(property=prop).update(is_active=False)
    get_user_model().objects.filter(default_property=prop).update(default_property=fresh)
    bump_version()
    audit.log(
        AuditLog.Action.RESTORE,
        fresh,
        changes={"archivado": prop.pk},
        user=user,
        property=fresh,
        reason=_("Restablecer datos de práctica"),
    )
    return fresh


def run_in_background(fn, *args, **kwargs):
    """Cargar un hotel completo toma minutos contra Supabase: se hace fuera de la petición."""

    def target():
        close_old_connections()
        try:
            fn(*args, **kwargs)
        finally:
            close_old_connections()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


# -- Escenarios (RF-SIM-03) --------------------------------------------------


@transaction.atomic
def start_scenario(prop, code, user) -> ScenarioRun:
    scenario = SCENARIOS.get(code)
    if scenario is None:
        raise ValidationError(_("Escenario desconocido."))
    run = ScenarioRun.objects.create(property=prop, scenario=code, started_by=user)
    if scenario.setup:
        run.data = scenario.setup(run, user) or {}
        run.save(update_fields=["data"])
    if not run.data.get("error"):
        from apps.comms.services import notify_role

        for role in ("receptionist", "manager"):
            notify_role(
                prop,
                role,
                _("Escenario de práctica: %(t)s") % {"t": scenario.title},
                run.data.get("story") or str(scenario.summary),
                url="/aula/",
            )
    return run


def refresh_run(run: ScenarioRun):
    steps = progress(run)
    if steps and all(done for _step, done in steps) and run.completed_at is None:
        run.completed_at = timezone.now()
        run.save(update_fields=["completed_at"])
    return steps


# -- Generador de eventos (RF-SIM-04) ----------------------------------------

WALK_IN_NAMES = [
    ("Oliver", "Wright", "GB"),
    ("Chiara", "Bianchi", "IT"),
    ("Mateo", "López", "AR"),
    ("Akira", "Sato", "JP"),
    ("Léa", "Dubois", "FR"),
    ("Noah", "Becker", "DE"),
]


def _event(prop, kind, message, user, roles=("receptionist", "manager")) -> PracticeEvent:
    from apps.comms.services import notify_role

    ev = PracticeEvent.objects.create(property=prop, kind=kind, message=message[:255], created_by=user)
    for role in roles:
        notify_role(prop, role, _("Evento de práctica"), message, url="/aula/", level="warning")
    return ev


def event_walk_ins(prop, user, n=2):
    from apps.guests.models import Guest

    names = random.sample(WALK_IN_NAMES, k=min(n, len(WALK_IN_NAMES)))
    for i, (first, last, country) in enumerate(names):
        email = f"walkin.{first.lower()}.{timezone.now():%H%M}{i}@aula.example"
        Guest.objects.create(
            first_name=first,
            last_name=last,
            nationality=country,
            residence_country=country,
            language="en",
            email=email,
            doc_type="7",
        )
    who = ", ".join(f"{f} {lname}" for f, lname, _c in names)
    return _event(
        prop,
        "walk_ins",
        _("Llegan %(n)s walk-ins sin reserva: %(who)s. Véndales habitación.") % {"n": len(names), "who": who},
        user,
    )


def event_agency_cancel(prop, user):
    from apps.reservations.models import Reservation
    from apps.reservations.services import cancel_reservation

    today = prop.current_business_date()
    future = Reservation.objects.filter(
        property=prop, status__in=["confirmed", "guaranteed"], arrival__gt=today
    )
    r = (
        future.filter(channel__in=["agency", "booking", "expedia", "airbnb"]).order_by("arrival").first()
        or future.order_by("arrival").first()
    )
    if r is None:
        raise ValidationError(_("No hay reservas futuras para cancelar."))
    cancel_reservation(r, _("La agencia canceló (evento de práctica)"), user=user, waive_penalty=True)
    return _event(
        prop,
        "agency_cancel",
        _(
            "La agencia canceló la reserva %(c)s de %(g)s (llegada %(d)s). "
            "Revise la disponibilidad y el depósito."
        )
        % {"c": r.code, "g": r.guest, "d": r.arrival.strftime("%d/%m")},
        user,
    )


def event_sunat_down(prop, user, down=True):
    from apps.billing.models import SimulationSettings

    sim, _created = SimulationSettings.objects.get_or_create(property=prop)
    sim.connection_down = down
    sim.save(update_fields=["connection_down"])
    msg = (
        _("SUNAT no responde: los comprobantes quedan pendientes. Reenvíelos cuando vuelva.")
        if down
        else _("SUNAT volvió: reenvíe los comprobantes pendientes.")
    )
    return _event(prop, "sunat_down" if down else "sunat_up", msg, user, roles=("receptionist", "accountant"))


def event_stock_out(prop, user):
    from apps.inventory import services as inv
    from apps.inventory.models import Stock

    stock = (
        Stock.objects.filter(warehouse__property=prop, quantity__gt=0, warehouse__kind__in=["kitchen", "bar"])
        .select_related("warehouse", "item")
        .order_by("?")
        .first()
    )
    if stock is None:
        raise ValidationError(_("No hay insumos con stock para agotar."))
    inv.adjust(stock.warehouse, stock.item, 0, reason=_("Evento de práctica: se acabó el insumo"), user=user)
    return _event(
        prop,
        "stock_out",
        _("Se acabó %(i)s en %(w)s. Pida reposición o cambie la carta.")
        % {"i": stock.item, "w": stock.warehouse},
        user,
        roles=("storekeeper", "pos", "manager"),
    )


EVENTS = {
    "walk_ins": (_("Llegan walk-ins"), event_walk_ins),
    "agency_cancel": (_("Una agencia cancela"), event_agency_cancel),
    "sunat_down": (_("Falla SUNAT"), event_sunat_down),
    "sunat_up": (_("SUNAT vuelve"), lambda prop, user: event_sunat_down(prop, user, down=False)),
    "stock_out": (_("Se acaba un insumo"), event_stock_out),
}


def fire(prop, kind, user) -> PracticeEvent:
    if kind not in EVENTS:
        raise ValidationError(_("Evento desconocido."))
    with transaction.atomic():
        return EVENTS[kind][1](prop, user)


# -- Panel del docente (RF-SIM-05) -------------------------------------------

ERROR_ACTIONS = [AuditLog.Action.VOID, AuditLog.Action.LOGIN_FAILED]


def student_progress(properties, days=30):
    """Avance por alumno: acciones, anulaciones (errores corregidos), escenarios y descuadres."""
    from apps.accounts.models import PropertyAccess
    from apps.folio.models import CashSession

    since = timezone.now() - timedelta(days=days)
    result = []
    for prop in properties:
        actions = {
            row["user_id"]: row
            for row in AuditLog.objects.filter(property=prop, timestamp__gte=since)
            .exclude(user__isnull=True)
            .values("user_id")
            .annotate(
                total=Count("pk"),
                errors=Count("pk", filter=Q(action__in=ERROR_ACTIONS)),
                discounts=Count("pk", filter=Q(action=AuditLog.Action.DISCOUNT)),
            )
        }
        cash = {
            row["user_id"]: row["n"]
            for row in CashSession.objects.filter(property=prop, created_at__gte=since)
            .exclude(difference=0)
            .values("user_id")
            .annotate(n=Count("pk"))
        }
        members = []
        for access in (
            PropertyAccess.objects.filter(property=prop, is_active=True)
            .exclude(role__code="teacher")
            .select_related("user", "role")
        ):
            row = actions.get(access.user_id, {})
            members.append(
                {
                    "user": access.user,
                    "role": access.role,
                    "actions": row.get("total", 0),
                    "voids": row.get("errors", 0),
                    "discounts": row.get("discounts", 0),
                    "cash_diff": cash.get(access.user_id, 0),
                }
            )
        runs = list(ScenarioRun.objects.filter(property=prop).order_by("-created_at")[:10])
        result.append(
            {
                "property": prop,
                "members": members,
                "runs": runs,
                "completed": sum(1 for r in runs if r.completed_at),
                "events": PracticeEvent.objects.filter(property=prop)[:5],
            }
        )
    return result


def recent_actions(prop, user_id, limit=50):
    return AuditLog.objects.filter(property=prop, user_id=user_id).order_by("-timestamp")[:limit]
