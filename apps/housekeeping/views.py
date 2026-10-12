from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.reports import services as rep
from apps.rooms.models import Room

from . import services
from .models import CleaningTask, LinenMovement, LinenType, LostItem, MinibarItem


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


class LostItemForm(PropertyModelForm):
    class Meta:
        model = LostItem
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            "found_at": forms.DateInput(attrs={"type": "date"}),
            "returned_at": forms.DateInput(attrs={"type": "date"}),
        }


lost_crud = Crud(
    model=LostItem,
    module="housekeeping",
    form_class=LostItemForm,
    columns=[
        (gettext_lazy("Fecha"), "found_at"),
        (gettext_lazy("Objeto"), "description"),
        (gettext_lazy("Lugar"), "location"),
        (gettext_lazy("Hab."), "room.number"),
        (gettext_lazy("Estado"), "status"),
        (gettext_lazy("Dueño"), "owner_name"),
    ],
    search=["description", "location", "owner_name"],
    filters=["status"],
    select_related=["room"],
    help_text=gettext_lazy("Objetos perdidos y encontrados con foto y entrega (RF-HK-06)."),
)
linen_crud = Crud(
    model=LinenType,
    module="housekeeping",
    columns=[
        (gettext_lazy("Prenda"), "name"),
        (gettext_lazy("Stock ideal"), "par_level"),
        (gettext_lazy("Activa"), "is_active"),
    ],
)
minibar_crud = Crud(
    model=MinibarItem,
    module="housekeeping",
    columns=[
        (gettext_lazy("Artículo"), "name"),
        (gettext_lazy("Precio"), "price"),
        (gettext_lazy("Activo"), "is_active"),
    ],
)


def _maids(property_obj):
    User = get_user_model()  # noqa: N806
    return User.objects.filter(
        property_accesses__property=property_obj,
        property_accesses__role__code="housekeeping",
        property_accesses__is_active=True,
        is_active=True,
    ).distinct()


@require_perm("housekeeping.view")
def board(request):
    """Tablero de la gobernanta: plan del día, asignación y estados (RF-HK-02)."""
    prop = request.property
    day = prop.current_business_date()
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "housekeeping.edit"):
            raise PermissionDenied
        try:
            if request.POST.get("action") == "generate":
                tasks = services.generate_daily_tasks(prop, day)
                messages.success(request, _("Plan generado: %(n)s tareas.") % {"n": len(tasks)})
            elif request.POST.get("action") == "assign":
                maids = _maids(prop).filter(pk__in=request.POST.getlist("maids"))
                load = services.assign_balanced(prop, day, maids)
                messages.success(
                    request,
                    _("Tareas repartidas (créditos por mucama: %(l)s).")
                    % {"l": ", ".join(str(v) for v in load.values())},
                )
            elif request.POST.get("action") == "reassign":
                task = get_object_or_404(CleaningTask, pk=request.POST["task"], property=prop)
                task.assigned_to_id = request.POST.get("maid") or None
                task.save(update_fields=["assigned_to"])
            elif request.POST.get("action") == "deep":
                room = get_object_or_404(Room, pk=request.POST["room"], property=prop)
                services._get_or_create_task(room, day, CleaningTask.Kind.DEEP, 5, _("Programada"))
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("housekeeping:board")
    tasks = CleaningTask.objects.filter(property=prop, date=day).select_related(
        "room__room_type", "assigned_to"
    )
    from apps.rooms.services import room_board, summary

    rooms = room_board(prop, day)
    return render(
        request,
        "housekeeping/board.html",
        {
            "day": day,
            "tasks": tasks,
            "maids": _maids(prop),
            "summary": summary(rooms),
            "rooms": rooms,
            "done": tasks.filter(status__in=["done", "inspected"]).count(),
        },
    )


@require_perm("housekeeping.view")
def my_tasks(request):
    """Vista de celular para la mucama: solo sus habitaciones (sección 3)."""
    day = request.property.current_business_date()
    tasks = CleaningTask.objects.filter(
        property=request.property, date=day, assigned_to=request.user
    ).select_related("room__room_type")
    return render(request, "housekeeping/my_tasks.html", {"tasks": tasks, "day": day})


@require_perm("housekeeping.view")
def task_detail(request, pk):
    task = get_object_or_404(CleaningTask.objects.select_related("room"), pk=pk, property=request.property)
    is_supervisor = request.user.has_pms_perm(request.property, "housekeeping.edit") and (
        request.user.is_superuser
        or getattr(request.user.role_for(request.property), "code", "") != "housekeeping"
        or task.assigned_to_id != request.user.pk
    )
    if task.assigned_to_id not in (None, request.user.pk) and not request.user.has_pms_perm(
        request.property, "housekeeping.edit"
    ):
        raise PermissionDenied
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "start":
                services.start_task(task, request.user)
            elif action == "finish":
                checklist = {
                    item["label"]: bool(request.POST.get(f"chk-{i}"))
                    for i, item in enumerate(task.checklist_items)
                }
                services.finish_task(task, request.user, checklist, request.POST.get("notes", ""))
                messages.success(
                    request, _("Habitación %(n)s lista. Se avisó a recepción.") % {"n": task.room.number}
                )
            elif action in ("approve", "reject"):
                services.inspect_task(
                    task,
                    request.user,
                    action == "approve",
                    request.POST.get("notes", ""),
                    request.FILES.get("photo"),
                )
        except ValidationError as exc:
            _errors(request, exc)
        return redirect("housekeeping:task_detail", pk=task.pk)
    reservation = None
    from apps.reservations.models import Reservation

    reservation = Reservation.objects.filter(room=task.room, status="checked_in").first()
    return render(
        request,
        "housekeeping/task_detail.html",
        {
            "task": task,
            "inventory": task.room.inventory.all(),
            "is_supervisor": is_supervisor,
            "reservation": reservation,
            "minibar": MinibarItem.objects.filter(property=request.property, is_active=True),
        },
    )


@require_POST
@require_perm("housekeeping.edit")
def minibar_post(request):
    """RF-HK-05: registra consumo de minibar en el folio del huésped."""
    from apps.reservations.models import Reservation

    r = get_object_or_404(Reservation, pk=request.POST.get("reservation"), property=request.property)
    items = []
    for item in MinibarItem.objects.filter(property=request.property, is_active=True):
        qty = int(request.POST.get(f"qty-{item.pk}") or 0)
        if qty:
            items.append((item, qty))
    try:
        charges = services.post_minibar(r, items, request.user)
        messages.success(request, _("Minibar cargado: %(n)s artículos.") % {"n": len(charges)})
    except ValidationError as exc:
        _errors(request, exc)
    return redirect(request.POST.get("next") or "housekeeping:board")


@require_perm("housekeeping.view")
def linen(request):
    """RF-HK-07: lencería, lavandería y stock."""
    prop = request.property
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "housekeeping.edit"):
            raise PermissionDenied
        linen_type = get_object_or_404(LinenType, pk=request.POST.get("linen"), property=prop)
        LinenMovement.objects.create(
            property=prop,
            linen=linen_type,
            direction=request.POST["direction"],
            quantity=int(request.POST.get("quantity") or 0),
            floor=request.POST.get("floor") or None,
            notes=request.POST.get("notes", ""),
        )
        messages.success(request, _("Movimiento registrado."))
        return redirect("housekeeping:linen")
    return render(
        request,
        "housekeeping/linen.html",
        {
            "stock": services.linen_stock(prop),
            "types": LinenType.objects.filter(property=prop, is_active=True),
            "directions": LinenMovement.Direction.choices,
            "movements": LinenMovement.objects.filter(property=prop).select_related("linen", "created_by")[
                :40
            ],
        },
    )


@require_perm("housekeeping.view")
def minibar(request):
    return render(
        request,
        "housekeeping/minibar.html",
        {
            "in_house": rep.in_house(request.property),
            "items": MinibarItem.objects.filter(property=request.property, is_active=True),
        },
    )
