from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.billing import services as billing
from apps.core.crud import Crud, PropertyModelForm
from apps.folio.models import Payment
from apps.reports import services as rep

from . import services
from .models import BreakfastLog, MenuCategory, MenuItem, Order, OrderItem, Outlet, Table


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


class MenuItemForm(PropertyModelForm):
    class Meta:
        model = MenuItem
        exclude = ["property", "created_by", "updated_by"]
        widgets = {"outlets": forms.CheckboxSelectMultiple}


outlet_crud = Crud(
    model=Outlet,
    module="pos",
    columns=[
        (gettext_lazy("Nombre"), "name"),
        (gettext_lazy("Tipo"), "kind"),
        (gettext_lazy("Activo"), "is_active"),
    ],
)
category_crud = Crud(
    model=MenuCategory,
    module="pos",
    columns=[
        (gettext_lazy("Nombre"), "name"),
        (gettext_lazy("Inglés"), "name_en"),
        (gettext_lazy("Orden"), "sort_order"),
    ],
)
menu_crud = Crud(
    model=MenuItem,
    module="pos",
    form_class=MenuItemForm,
    columns=[
        (gettext_lazy("Plato"), "name"),
        (gettext_lazy("Categoría"), "category"),
        (gettext_lazy("Precio"), "price"),
        (gettext_lazy("Prepara"), "station"),
        (gettext_lazy("Alérgenos"), "allergens"),
        (gettext_lazy("Disponible"), "is_available"),
    ],
    search=["name", "name_en"],
    filters=["category", "station", "is_available"],
    select_related=["category"],
)


class TableForm(PropertyModelForm):
    class Meta:
        model = Table
        fields = ["outlet", "number", "seats", "pos_x", "pos_y", "is_active"]


table_crud = Crud(
    model=Table,
    module="pos",
    form_class=TableForm,
    property_scoped=False,
    columns=[
        (gettext_lazy("Punto de venta"), "outlet"),
        (gettext_lazy("Mesa"), "number"),
        (gettext_lazy("Asientos"), "seats"),
    ],
)


def _table_qs(request):
    return Table.objects.filter(outlet__property=request.property)


table_crud.queryset = lambda request: _table_qs(request).select_related("outlet")


@require_perm("pos.view")
def outlets(request):
    items = Outlet.objects.filter(property=request.property, is_active=True)
    if len(items) == 1:
        return redirect("pos:floor", pk=items[0].pk)
    return render(request, "pos/outlets.html", {"outlets": items})


@require_perm("pos.view")
def floor(request, pk):
    """RF-POS-02: mapa de mesas del punto de venta."""
    outlet = get_object_or_404(Outlet, pk=pk, property=request.property)
    open_orders = {
        o.table_id: o for o in Order.objects.filter(outlet=outlet, status="open", table__isnull=False)
    }
    tables = [{"t": t, "order": open_orders.get(t.pk)} for t in outlet.tables.filter(is_active=True)]
    others = Order.objects.filter(outlet=outlet, status="open", table__isnull=True).select_related(
        "reservation__room"
    )
    return render(
        request,
        "pos/floor.html",
        {
            "outlet": outlet,
            "tables": tables,
            "others": others,
            "outlets": Outlet.objects.filter(property=request.property, is_active=True),
            "in_house": rep.in_house(request.property),
        },
    )


@require_POST
@require_perm("pos.create")
def order_open(request, pk):
    outlet = get_object_or_404(Outlet, pk=pk, property=request.property)
    table = Table.objects.filter(pk=request.POST.get("table"), outlet=outlet).first()
    reservation = None
    if request.POST.get("reservation"):
        from apps.reservations.models import Reservation

        reservation = get_object_or_404(
            Reservation, pk=request.POST["reservation"], property=request.property
        )
    try:
        order = services.open_order(
            outlet,
            user=request.user,
            table=table,
            covers=int(request.POST.get("covers") or 1),
            reservation=reservation,
        )
        return redirect("pos:order", pk=order.pk)
    except ValidationError as exc:
        _errors(request, exc)
        return redirect("pos:floor", pk=outlet.pk)


def _order(request, pk) -> Order:
    return get_object_or_404(
        Order.objects.select_related("outlet", "table", "reservation__room", "reservation__guest"),
        pk=pk,
        property=request.property,
    )


@require_perm("pos.view")
def order(request, pk):
    o = _order(request, pk)
    categories = MenuCategory.objects.filter(property=request.property).prefetch_related("items")
    menu = []
    for c in categories:
        items = [i for i in c.items.all() if i.is_active and o.outlet in i.outlets.all()]
        if items:
            menu.append({"category": c, "items": items})
    return render(
        request,
        "pos/order.html",
        {
            "o": o,
            "menu": menu,
            "items": o.items.select_related("menu_item"),
            "methods": [m for m in Payment.Method.choices if m[0] != "ledger"],
            "in_house": rep.in_house(request.property),
        },
    )


def _dec(v):
    try:
        return Decimal(str(v or "0").replace(",", ""))
    except InvalidOperation as exc:
        raise ValidationError(_("Monto inválido.")) from exc


@require_POST
@require_perm("pos.create")
def order_action(request, pk, action):
    o = _order(request, pk)
    try:
        if action == "add":
            item = get_object_or_404(MenuItem, pk=request.POST.get("item"), property=request.property)
            services.add_item(o, item, int(request.POST.get("qty") or 1), request.POST.get("notes", ""))
            if request.htmx:
                return render(
                    request, "pos/partials/items.html", {"o": o, "items": o.items.select_related("menu_item")}
                )
        elif action == "send":
            n = services.send_to_kitchen(o)
            messages.success(request, _("%(n)s platos enviados a cocina/barra.") % {"n": n})
        elif action == "void_item":
            item = get_object_or_404(OrderItem, pk=request.POST.get("item"), order=o)
            services.void_item(item, request.POST.get("reason") or _("Anulado por el mozo"), request.user)
        elif action == "split":
            child = services.split_order(o, [int(x) for x in request.POST.getlist("items")], request.user)
            messages.success(request, _("Cuenta dividida: %(n)s") % {"n": child.number})
            return redirect("pos:order", pk=child.pk)
        elif action == "room":
            from apps.reservations.models import Reservation

            r = get_object_or_404(Reservation, pk=request.POST.get("reservation"), property=request.property)
            services.charge_to_room(o, r, user=request.user, signature=request.POST.get("signature", ""))
            messages.success(
                request, _("Cargado a la habitación %(n)s.") % {"n": r.room.number if r.room else ""}
            )
            return redirect("pos:floor", pk=o.outlet_id)
        elif action == "pay":
            payments = []
            for i in range(3):
                method, amount = request.POST.get(f"method{i}"), request.POST.get(f"amount{i}")
                if method and amount and _dec(amount) > 0:
                    payments.append((method, _dec(amount)))
            doc_type = request.POST.get("doc_type", "03")
            customer = None
            if request.POST.get("customer_doc") or doc_type == "01":
                customer = billing.Customer(
                    "6" if doc_type == "01" else request.POST.get("customer_doc_type", "1"),
                    request.POST.get("customer_doc", "").strip(),
                    request.POST.get("customer_name") or _("Clientes varios"),
                    request.POST.get("customer_address", ""),
                )
            o, invoice = services.pay_order(
                o,
                payments,
                user=request.user,
                tip=_dec(request.POST.get("tip")),
                doc_type=doc_type,
                customer=customer,
            )
            messages.success(request, _("Cuenta cobrada. Comprobante %(n)s.") % {"n": invoice.full_number})
            return redirect("pos:floor", pk=o.outlet_id)
        elif action == "cancel":
            if not request.user.has_pms_perm(request.property, "pos.void"):
                raise PermissionDenied
            o.status = Order.Status.CANCELLED
            o.save(update_fields=["status"])
            return redirect("pos:floor", pk=o.outlet_id)
    except (ValidationError, PermissionDenied) as exc:
        _errors(request, exc)
    return redirect("pos:order", pk=o.pk)


@require_perm("pos.view")
def precheck(request, pk):
    """RF-POS-08: precuenta imprimible."""
    o = _order(request, pk)
    return render(
        request,
        "pos/precheck.html",
        {"o": o, "items": o.items.exclude(status="void").select_related("menu_item")},
    )


@require_perm("pos.view")
def ticket(request, pk):
    """RF-POS-08: comanda impresa para cocina/barra."""
    o = _order(request, pk)
    station = request.GET.get("station", "kitchen")
    items = o.items.filter(station=station).exclude(status="void").select_related("menu_item")
    return render(request, "pos/ticket.html", {"o": o, "items": items, "station": station})


@require_perm("pos.view")
def kds(request):
    """RF-POS-08: pantalla de cocina (KDS) con actualización automática."""
    station = request.GET.get("station", "kitchen")
    if request.method == "POST":
        item = get_object_or_404(OrderItem, pk=request.POST.get("item"), order__property=request.property)
        services.advance_item(item)
    items = (
        OrderItem.objects.filter(
            order__property=request.property, station=station, status__in=["sent", "preparing", "ready"]
        )
        .select_related("order__table", "order__outlet", "menu_item")
        .order_by("sent_at")
    )
    template = "pos/partials/kds_items.html" if request.htmx or request.method == "POST" else "pos/kds.html"
    return render(request, template, {"items": items, "station": station, "now": timezone.now()})


@require_perm("pos.view")
def breakfast(request):
    """RF-POS-06: control de desayunos incluidos y para llevar (Machu Picchu)."""
    prop = request.property
    day = prop.current_business_date()
    if request.method == "POST":
        from apps.reservations.models import Reservation

        r = get_object_or_404(Reservation, pk=request.POST.get("reservation"), property=prop)
        log, _c = BreakfastLog.objects.get_or_create(
            property=prop,
            reservation=r,
            date=day,
            kind=request.POST.get("kind", "restaurant"),
            defaults={
                "pax": int(request.POST.get("pax") or r.adults + r.children),
                "notes": request.POST.get("notes", ""),
            },
        )
        if request.POST.get("serve"):
            log.served, log.served_at = True, timezone.now()
            log.save()
        return redirect("pos:breakfast")
    guests = services.breakfast_list(prop, day)
    logs = {(b.reservation_id, b.kind): b for b in BreakfastLog.objects.filter(property=prop, date=day)}
    rows = [
        {
            "r": r,
            "rest": logs.get((r.pk, "restaurant")),
            "box": logs.get((r.pk, "box")),
            "early": logs.get((r.pk, "early")),
            "train": r.train_date == day,
        }
        for r in guests
    ]
    tomorrow_box = [r for r in rep.in_house(prop) if r.train_date and (r.train_date - day).days == 1]
    return render(
        request,
        "pos/breakfast.html",
        {
            "rows": rows,
            "day": day,
            "tomorrow_box": tomorrow_box,
            "served": sum(1 for r in rows if r["rest"] and r["rest"].served),
        },
    )


def public_menu(request, pk):
    """RF-POS-03: carta digital pública en español, inglés y portugués (QR en la mesa)."""
    outlet = get_object_or_404(Outlet, pk=pk, is_active=True)
    lang = request.GET.get("lang", "es")
    if lang not in ("es", "en", "pt-br"):
        lang = "es"
    with translation.override(lang):
        cats = []
        for c in MenuCategory.objects.filter(property=outlet.property).prefetch_related("items"):
            items = [i for i in c.items.all() if i.is_active and i.is_available and outlet in i.outlets.all()]
            if items:
                cats.append({"c": c, "items": items})
        return render(request, "pos/public_menu.html", {"outlet": outlet, "cats": cats, "lang": lang})
