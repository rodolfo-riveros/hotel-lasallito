from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.inventory.models import Item

from . import services
from .models import Asset, PreventivePlan, WorkOrder


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


class AssetForm(PropertyModelForm):
    class Meta:
        model = Asset
        exclude = ["property", "created_by", "updated_by"]
        widgets = {"acquisition_date": forms.DateInput(attrs={"type": "date"})}


asset_crud = Crud(
    model=Asset,
    module="maintenance",
    form_class=AssetForm,
    columns=[
        (gettext_lazy("Código"), "code"),
        (gettext_lazy("Equipo / activo"), "name"),
        (gettext_lazy("Tipo"), "kind"),
        (gettext_lazy("Ubicación"), "location"),
        (gettext_lazy("Valor"), "value"),
        (gettext_lazy("En uso"), "is_active"),
    ],
    search=["code", "name", "serial"],
    filters=["kind"],
    select_related=["room"],
    help_text=gettext_lazy(
        "Mobiliario, equipos y su ubicación por habitación o área (RF-ALM-09, RF-MAN-02)."
    ),
)


class PlanForm(PropertyModelForm):
    class Meta:
        model = PreventivePlan
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            "next_due": forms.DateInput(attrs={"type": "date"}),
            "checklist": forms.Textarea(attrs={"rows": 3}),
        }


plan_crud = Crud(
    model=PreventivePlan,
    module="maintenance",
    form_class=PlanForm,
    columns=[
        (gettext_lazy("Tarea"), "name"),
        (gettext_lazy("Equipo"), "asset"),
        (gettext_lazy("Cada (días)"), "frequency_days"),
        (gettext_lazy("Próxima"), "next_due"),
        (gettext_lazy("Responsable"), "assigned_to"),
        (gettext_lazy("Activo"), "is_active"),
    ],
    select_related=["asset", "assigned_to"],
    list_template="maintenance/plan_list.html",
)


class WorkOrderForm(PropertyModelForm):
    class Meta:
        model = WorkOrder
        fields = ["title", "description", "room", "asset", "priority", "source", "assigned_to", "block_room"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model

        self.fields["assigned_to"].queryset = (
            get_user_model()
            .objects.filter(
                property_accesses__property=self.property, property_accesses__role__code="maintenance"
            )
            .distinct()
        )


@require_perm("maintenance.view")
def wo_list(request):
    """RF-MAN-01: órdenes de trabajo."""
    qs = WorkOrder.objects.filter(property=request.property).select_related("room", "asset", "assigned_to")
    status = request.GET.get("status", "open_all")
    if status == "open_all":
        qs = qs.exclude(status__in=["done", "cancelled"])
    elif status:
        qs = qs.filter(status=status)
    mine = request.GET.get("mias")
    if mine:
        qs = qs.filter(assigned_to=request.user)
    return render(
        request,
        "maintenance/wo_list.html",
        {"items": qs[:200], "status": status, "statuses": WorkOrder.Status.choices},
    )


@require_perm("maintenance.create")
def wo_create(request):
    form = WorkOrderForm(
        request.POST or None,
        property=request.property,
        initial={"room": request.GET.get("room"), "source": request.GET.get("origen", "other")},
    )
    if request.method == "POST" and form.is_valid():
        try:
            wo = services.open_work_order(request.property, user=request.user, **form.cleaned_data)
            messages.success(request, _("Orden %(n)s creada.") % {"n": wo.number})
            return redirect("maintenance:wo_detail", pk=wo.pk)
        except ValidationError as exc:
            _errors(request, exc)
    return render(
        request,
        "core/simple_form.html",
        {
            "form": form,
            "title": _("Nueva orden de trabajo"),
            "back": "/mantenimiento/",
            "submit": _("Crear orden"),
            "subtitle": _("Si marca bloquear, la habitación no se vende hasta cerrar la orden (RF-MAN-03)."),
        },
    )


@require_perm("maintenance.view")
def wo_detail(request, pk):
    wo = get_object_or_404(
        WorkOrder.objects.select_related("room", "asset", "assigned_to", "room_block"),
        pk=pk,
        property=request.property,
    )
    if request.method == "POST":
        if not request.user.has_pms_perm(request.property, "maintenance.edit"):
            raise PermissionDenied
        action = request.POST.get("action")
        try:
            if action == "start":
                services.start(wo, request.user)
            elif action == "part":
                item = get_object_or_404(Item, pk=request.POST.get("item"), property=request.property)
                services.add_part(wo, item, Decimal(request.POST.get("quantity") or "0"), request.user)
                messages.success(request, _("Repuesto descontado del almacén."))
            elif action == "hold":
                wo.status = WorkOrder.Status.ON_HOLD
                wo.save(update_fields=["status"])
            elif action == "close":
                services.close(
                    wo,
                    request.user,
                    request.POST.get("resolution", ""),
                    Decimal(request.POST.get("labor_cost") or "0"),
                )
                messages.success(request, _("Orden cerrada."))
        except (ValidationError, PermissionDenied, InvalidOperation) as exc:
            _errors(request, exc)
        return redirect("maintenance:wo_detail", pk=wo.pk)
    return render(
        request,
        "maintenance/wo_detail.html",
        {
            "wo": wo,
            "parts": wo.parts.select_related("item"),
            "items": Item.objects.filter(property=request.property, is_active=True),
            "history": (
                WorkOrder.objects.filter(property=request.property, room=wo.room).exclude(pk=wo.pk)[:10]
                if wo.room
                else []
            ),
        },
    )


@require_perm("maintenance.view")
def costs(request):
    """RF-MAN-04: historial y costo por habitación y por equipo."""
    by_room, by_asset = services.cost_history(request.property)
    return render(request, "maintenance/costs.html", {"by_room": by_room, "by_asset": by_asset})


@require_perm("maintenance.create")
def generate(request):
    if request.method == "POST":
        created = services.generate_preventive(request.property)
        messages.success(request, _("%(n)s órdenes preventivas generadas.") % {"n": len(created)})
    return redirect("maintenance:plan_list")
