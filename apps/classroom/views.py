from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.accounts.middleware import SESSION_PROPERTY_KEY
from apps.core.models import Property

from . import services
from .models import PracticeEvent, ScenarioRun
from .scenarios import SCENARIOS


class PracticePropertyForm(forms.Form):
    name = forms.CharField(
        label=gettext_lazy("Nombre del hotel de práctica"),
        max_length=150,
        initial="Hotel La Sallito · Grupo A",
    )
    code = forms.SlugField(label=gettext_lazy("Código"), max_length=30, initial="aula-grupo-a")


def _runs(prop, limit=10):
    runs = list(ScenarioRun.objects.filter(property=prop).order_by("-created_at")[:limit])
    return [{"run": r, "scenario": SCENARIOS.get(r.scenario), "steps": services.refresh_run(r)} for r in runs]


@require_perm("classroom.view")
def panel(request):
    """RF-SIM-05: panel del docente. RF-SIM-03/04: escenarios y eventos del hotel activo."""
    prop = request.property
    properties = [p for p in request.user_properties if request.user.has_pms_perm(p, "classroom.view")]
    return render(
        request,
        "classroom/panel.html",
        {
            "runs": _runs(prop),
            "scenarios": SCENARIOS.values(),
            "events": services.EVENTS,
            "recent_events": PracticeEvent.objects.filter(property=prop)[:10],
            "students": services.student_progress(properties),
            "form": PracticePropertyForm(),
            "archived": Property.objects.filter(is_active=False, code__contains="-arch-").order_by("-pk")[
                :10
            ],
        },
    )


@require_POST
@require_perm("classroom.create")
def launch(request):
    try:
        run = services.start_scenario(request.property, request.POST.get("scenario", ""), request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        if run.data.get("error"):
            messages.error(request, run.data["error"])
        else:
            messages.success(request, _("Escenario lanzado: %(t)s.") % {"t": SCENARIOS[run.scenario].title})
    return redirect("classroom:panel")


@require_POST
@require_perm("classroom.create")
def fire_event(request):
    try:
        ev = services.fire(request.property, request.POST.get("kind", ""), request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, ev.message)
    return redirect("classroom:panel")


@require_POST
@require_perm("classroom.approve")
def create_property(request):
    """RF-SIM-02: crea el hotel aislado de un alumno o grupo y carga los datos de ejemplo en segundo plano."""
    form = PracticePropertyForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Revise el nombre y el código."))
        return redirect("classroom:panel")
    try:
        prop = services.create_practice_property(
            form.cleaned_data["name"],
            slugify(form.cleaned_data["code"]),
            template=request.property,
            user=request.user,
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("classroom:panel")
    services.run_in_background(services.load_sample_data, prop, request.user)
    messages.success(
        request,
        _(
            "Hotel %(p)s creado. Los datos de ejemplo se cargan en unos minutos; asigne a los "
            "alumnos desde Usuarios y roles."
        )
        % {"p": prop},
    )
    return redirect("classroom:panel")


@require_POST
@require_perm("classroom.approve")
def reset(request, pk):
    """RF-SIM-01: restablecer los datos del hotel. Lo anterior queda archivado (la auditoría no se borra)."""
    prop = get_object_or_404(Property, pk=pk, is_active=True)
    if prop not in request.user_properties or not request.user.has_pms_perm(prop, "classroom.approve"):
        raise PermissionDenied
    if request.POST.get("confirm") != prop.code:
        messages.error(request, _("Escriba el código del hotel para confirmar."))
        return redirect("classroom:panel")
    fresh = services.archive_and_clone(prop, request.user)
    services.run_in_background(services.load_sample_data, fresh, request.user)
    request.session.pop(SESSION_PROPERTY_KEY, None)
    messages.success(
        request, _("%(p)s restablecido. Los datos de ejemplo se cargan en unos minutos.") % {"p": fresh}
    )
    return redirect("classroom:panel")


@require_perm("classroom.view")
def student(request, prop_pk, user_pk):
    """RF-SIM-05: historial de acciones de un alumno."""
    prop = get_object_or_404(Property, pk=prop_pk)
    if prop not in request.user_properties:
        raise PermissionDenied
    from django.contrib.auth import get_user_model

    user = get_object_or_404(get_user_model(), pk=user_pk)
    return render(
        request,
        "classroom/student.html",
        {"prop": prop, "student": user, "logs": services.recent_actions(prop, user.pk, 100)},
    )


@login_required
def guide(request):
    """Guía paso a paso para el alumno: escenarios activos de su hotel."""
    if request.property is None:
        raise PermissionDenied
    return render(
        request,
        "classroom/guide.html",
        {"runs": [r for r in _runs(request.property, 5) if not r["run"].data.get("error")]},
    )
