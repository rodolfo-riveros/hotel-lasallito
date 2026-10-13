from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.reservations.models import Reservation

from . import services
from .models import Operator, Service, ServiceBooking

operator_crud = Crud(
    model=Operator,
    module="tours",
    columns=[
        (gettext_lazy("Operador"), "name"),
        (gettext_lazy("Contacto"), "contact_name"),
        (gettext_lazy("Correo"), "email"),
        (gettext_lazy("Activo"), "is_active"),
    ],
    search=["name"],
)


class ServiceForm(PropertyModelForm):
    class Meta:
        model = Service
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            "pickup_time": forms.TimeInput(attrs={"type": "time"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }


service_crud = Crud(
    model=Service,
    module="tours",
    form_class=ServiceForm,
    columns=[
        (gettext_lazy("Servicio"), "name"),
        (gettext_lazy("Tipo"), "kind"),
        (gettext_lazy("Operador"), "operator"),
        (gettext_lazy("Precio"), "price"),
        (gettext_lazy("Costo"), "cost"),
        (gettext_lazy("Web"), "is_public"),
        (gettext_lazy("Activo"), "is_active"),
    ],
    filters=["kind"],
    select_related=["operator"],
    help_text=gettext_lazy("Catálogo de tours y traslados (RF-TUR-01)."),
)


class SaleForm(forms.Form):
    service = forms.ModelChoiceField(label=gettext_lazy("Servicio"), queryset=Service.objects.none())
    reservation = forms.ModelChoiceField(
        label=gettext_lazy("Huésped en casa (se carga al folio)"),
        queryset=Reservation.objects.none(),
        required=False,
    )
    guest_name = forms.CharField(label=gettext_lazy("Pasajero (si no es huésped)"), required=False)
    date = forms.DateField(label=gettext_lazy("Fecha"), widget=forms.DateInput(attrs={"type": "date"}))
    pickup_time = forms.TimeField(
        label=gettext_lazy("Hora de recojo"), required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    pickup_point = forms.CharField(label=gettext_lazy("Punto de recojo"), initial="Lobby del hotel")
    pax = forms.IntegerField(label=gettext_lazy("Pasajeros"), min_value=1, initial=2)
    notes = forms.CharField(label=gettext_lazy("Notas (vuelo, tren, dieta)"), required=False)


@require_perm("tours.view")
def agenda(request):
    """RF-TUR-03/04: agenda diaria de recojos y alertas de tren."""
    prop = request.property
    try:
        day = date.fromisoformat(request.GET["fecha"])
    except (KeyError, ValueError):
        day = prop.current_business_date()
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "tours.edit"):
            raise PermissionDenied
        if request.POST.get("operator"):
            op = get_object_or_404(Operator, pk=request.POST["operator"], property=prop)
            n = services.send_agenda(prop, day, op)
            messages.success(request, _("Agenda enviada a %(o)s (%(n)s servicios).") % {"o": op, "n": n})
        elif request.POST.get("done"):
            ServiceBooking.objects.filter(pk=request.POST["done"], property=prop).update(status="done")
        elif request.POST.get("cancel"):
            sb = get_object_or_404(ServiceBooking, pk=request.POST["cancel"], property=prop)
            try:
                services.cancel_service(sb, request.user, _("Anulado en agenda"))
            except PermissionDenied:
                messages.error(
                    request, _("Anular el cargo del folio requiere permiso de anulación de folios.")
                )
        return redirect(f"{request.path}?fecha={day.isoformat()}")
    items = services.agenda(prop, day)
    operators = Operator.objects.filter(property=prop, is_active=True)
    return render(
        request,
        "tours/agenda.html",
        {
            "day": day,
            "items": items,
            "operators": operators,
            "prev": day - timedelta(days=1),
            "next": day + timedelta(days=1),
            "trains": services.train_alerts(prop, day),
        },
    )


@require_perm("tours.create")
def sell(request):
    """RF-TUR-02: venta desde el folio."""
    prop = request.property
    form = SaleForm(
        request.POST or None,
        initial={
            "date": prop.current_business_date() + timedelta(days=1),
            "reservation": request.GET.get("reserva"),
        },
    )
    form.fields["service"].queryset = Service.objects.filter(property=prop, is_active=True)
    form.fields["reservation"].queryset = Reservation.objects.filter(
        property=prop, status__in=["checked_in", "confirmed", "guaranteed"]
    ).select_related("guest", "room")
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        try:
            if not cd["reservation"] and not cd["guest_name"]:
                raise ValidationError(_("Elija un huésped o escriba el nombre del pasajero."))
            sb = services.book_service(
                cd["service"],
                date=cd["date"],
                pax=cd["pax"],
                reservation=cd["reservation"],
                guest_name=cd["guest_name"],
                pickup_time=cd["pickup_time"],
                pickup_point=cd["pickup_point"],
                notes=cd["notes"],
                user=request.user,
            )
            messages.success(request, _("Vendido: %(s)s.") % {"s": sb})
            return redirect(f"/tours/?fecha={cd['date'].isoformat()}")
        except ValidationError as exc:
            for m in exc.messages:
                messages.error(request, m)
    return render(
        request,
        "core/simple_form.html",
        {"form": form, "title": _("Vender tour o traslado"), "back": "/tours/", "submit": _("Vender")},
    )


@require_perm("tours.view")
def settlement(request):
    """RF-TUR-05: liquidación y comisiones por operador."""
    prop = request.property
    today = prop.current_business_date()
    try:
        start = date.fromisoformat(request.GET["start"])
        end = date.fromisoformat(request.GET["end"])
    except (KeyError, ValueError):
        start, end = today.replace(day=1), today + timedelta(days=1)
    return render(
        request,
        "tours/settlement.html",
        {"rows": services.settlement(prop, start, end), "start": start, "end": end},
    )
