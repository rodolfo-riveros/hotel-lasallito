from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.crud import Crud
from apps.core.models import AuditLog

from .forms import RoomBlockForm, RoomForm, RoomTypeForm
from .models import Room, RoomBlock, RoomInventoryItem, RoomType
from .services import room_board, summary

room_type_crud = Crud(
    model=RoomType,
    module="rooms",
    form_class=RoomTypeForm,
    columns=[
        (gettext_lazy("Código"), "code"),
        (gettext_lazy("Nombre"), "name"),
        (gettext_lazy("Adultos incluidos"), "base_occupancy"),
        (gettext_lazy("Máx."), "max_occupancy"),
        (gettext_lazy("Camas"), "beds"),
        (gettext_lazy("Activo"), "is_active"),
    ],
    search=["code", "name"],
)

room_crud = Crud(
    model=Room,
    module="rooms",
    form_class=RoomForm,
    columns=[
        (gettext_lazy("Número"), "number"),
        (gettext_lazy("Tipo"), "room_type"),
        (gettext_lazy("Piso"), "floor"),
        (gettext_lazy("Vista"), "view"),
        (gettext_lazy("Limpieza"), "hk_status"),
        (gettext_lazy("Oxígeno"), "has_oxygen"),
        (gettext_lazy("Activa"), "is_active"),
    ],
    search=["number", "location", "room_type__name"],
    filters=["room_type", "hk_status"],
    select_related=["room_type"],
)

block_crud = Crud(
    model=RoomBlock,
    module="rooms",
    form_class=RoomBlockForm,
    columns=[
        (gettext_lazy("Habitación"), "room.number"),
        (gettext_lazy("Tipo"), "kind"),
        (gettext_lazy("Desde"), "start_date"),
        (gettext_lazy("Hasta"), "end_date"),
        (gettext_lazy("Motivo"), "reason"),
        (gettext_lazy("Vigente"), "is_active"),
    ],
    search=["room__number", "reason"],
    filters=["kind", "is_active"],
    select_related=["room"],
    help_text=gettext_lazy("Las habitaciones bloqueadas no se pueden vender en esas fechas (RF-HAB-03)."),
)


@require_perm("rooms.view")
def rack(request):
    """Rack de habitaciones con estado combinado (RF-HAB-02, RF-HK-01)."""
    board = room_board(request.property)
    floors = {}
    for item in board:
        floors.setdefault(item["room"].floor, []).append(item)
    return render(
        request,
        "rooms/rack.html",
        {"floors": sorted(floors.items()), "summary": summary(board), "total": len(board)},
    )


@require_perm("rooms.view")
def room_inventory(request, pk):
    """RF-HAB-05: inventario de una habitación."""
    room = get_object_or_404(Room, pk=pk, property=request.property)
    if request.method == "POST":
        if not request.user.has_pms_perm(request.property, "rooms.edit"):
            raise PermissionDenied
        if request.POST.get("delete"):
            RoomInventoryItem.objects.filter(room=room, pk=request.POST["delete"]).delete()
        else:
            name = request.POST.get("name", "").strip()
            qty = int(request.POST.get("quantity") or 1)
            if name:
                item = RoomInventoryItem.objects.create(room=room, name=name, quantity=qty)
                audit.log(AuditLog.Action.CREATE, item, property=request.property)
        return redirect("rooms:room_inventory", pk=room.pk)
    return render(request, "rooms/room_inventory.html", {"room": room, "items": room.inventory.all()})


@require_POST
@require_perm("housekeeping.edit")
def set_hk_status(request, pk):
    """Cambio de estado de limpieza (también desde el celular, RF-HK-01)."""
    room = get_object_or_404(Room, pk=pk, property=request.property)
    status = request.POST.get("status")
    if status in Room.HKStatus.values:
        before = audit.snapshot(room, ["hk_status"])
        room.hk_status = status
        room.save()
        audit.log_changes(room, before)
        messages.success(
            request, _("Habitación %(n)s: %(s)s") % {"n": room.number, "s": room.get_hk_status_display()}
        )
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = "rooms:rack"
    return redirect(next_url)
