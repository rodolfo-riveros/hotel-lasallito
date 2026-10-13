from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.pos.models import MenuItem

from . import services
from .models import Item, ItemCategory, RecipeLine, Stock, StockCount, StockMovement, Warehouse, Waste


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


def _dec(value, field=""):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except InvalidOperation as exc:
        raise ValidationError(_("Número inválido %(f)s") % {"f": field}) from exc


warehouse_crud = Crud(
    model=Warehouse,
    module="inventory",
    columns=[
        (gettext_lazy("Código"), "code"),
        (gettext_lazy("Nombre"), "name"),
        (gettext_lazy("Tipo"), "kind"),
        (gettext_lazy("Activo"), "is_active"),
    ],
)
category_crud = Crud(model=ItemCategory, module="inventory", columns=[(gettext_lazy("Nombre"), "name")])


class ItemForm(PropertyModelForm):
    class Meta:
        model = Item
        exclude = ["property", "created_by", "updated_by", "last_cost"]


item_crud = Crud(
    model=Item,
    module="inventory",
    form_class=ItemForm,
    columns=[
        (gettext_lazy("Código"), "code"),
        (gettext_lazy("Artículo"), "name"),
        (gettext_lazy("Categoría"), "category"),
        (gettext_lazy("Unidad"), "unit"),
        (gettext_lazy("Mín."), "min_stock"),
        (gettext_lazy("Máx."), "max_stock"),
        (gettext_lazy("Último costo"), "last_cost"),
        (gettext_lazy("Perecible"), "is_perishable"),
    ],
    search=["code", "name"],
    filters=["category", "is_perishable"],
    select_related=["category"],
    help_text=gettext_lazy(
        "Catálogo con unidad de consumo, unidad de compra y stock mínimo y máximo (RF-ALM-02)."
    ),
)


class WasteForm(PropertyModelForm):
    class Meta:
        model = Waste
        fields = ["warehouse", "item", "quantity", "reason", "photo"]


waste_crud = Crud(
    model=Waste,
    module="inventory",
    form_class=WasteForm,
    columns=[
        (gettext_lazy("Fecha"), "created_at"),
        (gettext_lazy("Artículo"), "item"),
        (gettext_lazy("Cantidad"), "quantity"),
        (gettext_lazy("Motivo"), "reason"),
        (gettext_lazy("Estado"), "status"),
        (gettext_lazy("Aprobó"), "approved_by"),
    ],
    filters=["status"],
    select_related=["item", "approved_by"],
    list_template="inventory/waste_list.html",
    help_text=gettext_lazy("Mermas y bajas con foto; el gerente las aprueba antes de descontar (RF-ALM-08)."),
)


@require_perm("inventory.view")
def stock(request):
    """RF-ALM-01: stock por almacén, valorizado al costo promedio."""
    prop = request.property
    warehouses = Warehouse.objects.filter(property=prop, is_active=True)
    qs = Stock.objects.filter(warehouse__property=prop).select_related("item__category", "warehouse")
    wh = request.GET.get("warehouse")
    if wh:
        qs = qs.filter(warehouse_id=wh)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(item__name__icontains=q)
    rows = list(qs.order_by("item__name"))
    total = sum((s.value for s in rows), Decimal("0"))
    return render(
        request,
        "inventory/stock.html",
        {
            "rows": rows,
            "warehouses": warehouses,
            "wh": wh,
            "q": q,
            "total": total,
            "low": services.low_stock(prop).count(),
            "expiring": services.expiring_lots(prop).count(),
        },
    )


@require_perm("inventory.view")
def kardex(request, pk):
    """RF-ALM-04: kardex valorizado por artículo (y almacén)."""
    item = get_object_or_404(Item, pk=pk, property=request.property)
    moves = StockMovement.objects.filter(item=item).select_related("warehouse", "created_by")
    wh = request.GET.get("warehouse")
    if wh:
        moves = moves.filter(warehouse_id=wh)
    return render(
        request,
        "inventory/kardex.html",
        {
            "item": item,
            "moves": moves.order_by("-date", "-pk")[:300],
            "wh": wh,
            "warehouses": Warehouse.objects.filter(property=request.property),
            "stocks": item.stocks.select_related("warehouse"),
            "lots": item.lots.filter(quantity__gt=0).select_related("warehouse"),
        },
    )


class MovementForm(forms.Form):
    KINDS = [
        ("in", gettext_lazy("Ingreso")),
        ("out", gettext_lazy("Salida por requisición")),
        ("transfer", gettext_lazy("Transferencia")),
        ("adjust", gettext_lazy("Ajuste a cantidad")),
    ]
    kind = forms.ChoiceField(label=gettext_lazy("Operación"), choices=KINDS)
    warehouse = forms.ModelChoiceField(label=gettext_lazy("Almacén"), queryset=Warehouse.objects.none())
    target = forms.ModelChoiceField(
        label=gettext_lazy("Almacén destino (transferencia)"),
        queryset=Warehouse.objects.none(),
        required=False,
    )
    item = forms.ModelChoiceField(label=gettext_lazy("Artículo"), queryset=Item.objects.none())
    quantity = forms.DecimalField(label=gettext_lazy("Cantidad (unidad de consumo)"), min_value=0)
    unit_cost = forms.DecimalField(
        label=gettext_lazy("Costo unitario (ingresos)"), required=False, min_value=0
    )
    lot = forms.CharField(label=gettext_lazy("Lote"), required=False)
    expiry = forms.DateField(
        label=gettext_lazy("Vencimiento"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    reference = forms.CharField(label=gettext_lazy("Documento (guía, factura, vale)"), required=False)
    notes = forms.CharField(label=gettext_lazy("Motivo / notas"), required=False)

    def __init__(self, *args, property=None, **kwargs):
        super().__init__(*args, **kwargs)
        wh = Warehouse.objects.filter(property=property, is_active=True)
        self.fields["warehouse"].queryset = wh
        self.fields["target"].queryset = wh
        self.fields["item"].queryset = Item.objects.filter(property=property, is_active=True)


@require_perm("inventory.create")
def movement(request):
    """RF-ALM-03: ingresos, salidas por requisición, transferencias y ajustes."""
    form = MovementForm(
        request.POST or None, property=request.property, initial={"kind": request.GET.get("kind", "in")}
    )
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            if cd["kind"] == "in":
                services.receive(
                    cd["warehouse"],
                    cd["item"],
                    cd["quantity"],
                    cd["unit_cost"] or cd["item"].last_cost,
                    reference=cd["reference"],
                    notes=cd["notes"],
                    lot_code=cd["lot"],
                    expiry=cd["expiry"],
                )
            elif cd["kind"] == "out":
                services.issue(
                    cd["warehouse"], cd["item"], cd["quantity"], reference=cd["reference"], notes=cd["notes"]
                )
            elif cd["kind"] == "transfer":
                if not cd["target"]:
                    raise ValidationError(_("Elija el almacén de destino."))
                services.transfer(
                    cd["warehouse"], cd["target"], cd["item"], cd["quantity"], reference=cd["reference"]
                )
            else:
                services.adjust(
                    cd["warehouse"],
                    cd["item"],
                    cd["quantity"],
                    reason=cd["notes"],
                    user=request.user,
                    reference=cd["reference"],
                )
            messages.success(request, _("Movimiento registrado."))
            return redirect("inventory:kardex", pk=cd["item"].pk)
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    return render(
        request,
        "core/simple_form.html",
        {
            "form": form,
            "title": _("Movimiento de almacén"),
            "back": "/almacen/",
            "submit": _("Registrar"),
            "subtitle": _("El costo promedio ponderado se recalcula en cada ingreso (RF-ALM-04)."),
        },
    )


@require_perm("inventory.view")
def alerts(request):
    """RF-ALM-05/07: stock mínimo, vencimientos y sugerencia de pedido."""
    prop = request.property
    return render(
        request,
        "inventory/alerts.html",
        {
            "low": services.low_stock(prop),
            "expiring": services.expiring_lots(prop, 15),
            "suggested": services.suggested_orders(prop),
        },
    )


@require_perm("inventory.view")
def counts(request):
    prop = request.property
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "inventory.create"):
            raise PermissionDenied
        wh = get_object_or_404(Warehouse, pk=request.POST.get("warehouse"), property=prop)
        count = services.start_count(wh, request.user)
        return redirect("inventory:count_detail", pk=count.pk)
    return render(
        request,
        "inventory/counts.html",
        {
            "counts": StockCount.objects.filter(property=prop).select_related("warehouse")[:50],
            "warehouses": Warehouse.objects.filter(property=prop, is_active=True),
        },
    )


@require_perm("inventory.view")
def count_detail(request, pk):
    """RF-ALM-06: conteo físico (también desde el celular) y reporte de diferencias."""
    count = get_object_or_404(StockCount, pk=pk, property=request.property)
    lines = count.lines.select_related("item")
    if request.method == "POST" and count.status == "open":
        if not request.user.has_pms_perm(request.property, "inventory.edit"):
            raise PermissionDenied
        for line in lines:
            value = request.POST.get(f"line-{line.pk}")
            if value not in (None, ""):
                line.counted_qty = _dec(value)
                line.save(update_fields=["counted_qty"])
        if request.POST.get("close"):
            try:
                moves = services.close_count(count, request.user)
                messages.success(request, _("Inventario cerrado: %(n)s ajustes.") % {"n": len(moves)})
            except (ValidationError, PermissionDenied) as exc:
                _errors(request, exc)
        else:
            messages.success(request, _("Conteo guardado."))
        return redirect("inventory:count_detail", pk=count.pk)
    return render(request, "inventory/count_detail.html", {"count": count, "lines": lines})


@require_POST
@require_perm("inventory.view")
def waste_decide(request, pk):
    waste = get_object_or_404(Waste, pk=pk, property=request.property)
    try:
        services.decide_waste(waste, request.POST.get("decision") == "approve", request.user)
        messages.success(request, _("Merma revisada."))
    except (ValidationError, PermissionDenied) as exc:
        _errors(request, exc)
    return redirect("inventory:waste_list")


RecipeFormSet = forms.inlineformset_factory(
    MenuItem, RecipeLine, fields=["item", "quantity"], extra=3, can_delete=True
)


@require_perm("inventory.view")
def recipes(request):
    items = (
        MenuItem.objects.filter(property=request.property, is_active=True)
        .select_related("category")
        .prefetch_related("recipe__item")
    )
    rows = []
    for mi in items:
        cost = sum((ln.quantity * ln.item.last_cost for ln in mi.recipe.all()), Decimal("0"))
        net = mi.price / Decimal("1.18")
        rows.append(
            {
                "mi": mi,
                "cost": cost.quantize(Decimal("0.01")),
                "food_cost": (cost * 100 / net).quantize(Decimal("0.1")) if net else 0,
            }
        )
    return render(request, "inventory/recipes.html", {"rows": rows})


@require_perm("inventory.edit")
def recipe_edit(request, pk):
    """RF-POS-05: insumos por plato en gramos, litros o unidades."""
    mi = get_object_or_404(MenuItem, pk=pk, property=request.property)
    formset = RecipeFormSet(request.POST or None, instance=mi)
    for f in formset.forms:
        f.fields["item"].queryset = Item.objects.filter(property=request.property, is_active=True)
    if request.method == "POST" and formset.is_valid():
        formset.save()
        messages.success(request, _("Receta guardada."))
        return redirect("inventory:recipes")
    return render(request, "inventory/recipe_form.html", {"mi": mi, "formset": formset})


@require_perm("inventory.view")
def valuation(request):
    """Valorización por almacén y costo de alimentos del mes (RF-REP-03)."""
    prop = request.property
    today = prop.current_business_date()
    by_wh = (
        Stock.objects.filter(warehouse__property=prop)
        .values("warehouse__name")
        .annotate(value=Sum(F("quantity") * F("avg_cost")))
        .order_by("warehouse__name")
    )
    return render(
        request,
        "inventory/valuation.html",
        {
            "by_wh": by_wh,
            "food_cost": services.food_cost(prop, today.replace(day=1), today),
        },
    )
