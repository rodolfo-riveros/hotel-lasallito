from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.crud import PropertyModelForm
from apps.core.models import AuditLog
from apps.guests.forms import GuestForm, QuickGuestForm
from apps.rates.models import RatePlan
from apps.reports import services as rep
from apps.reservations.availability import free_rooms
from apps.reservations.models import Reservation
from apps.rooms.models import Room

from . import services
from .models import LuggageTicket, NightAudit, RoomMove, ShiftLog, WakeUpCall


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


# --------------------------------------------------------------------------
# Panel del día (RF-REC-01)
# --------------------------------------------------------------------------


@require_perm("frontdesk.view")
def panel(request):
    prop = request.property
    day = prop.current_business_date()
    tab = request.GET.get("tab", "arrivals")
    arrivals = rep.arrivals(prop, day)
    eta = request.GET.get("eta")
    if eta == "morning":
        arrivals = arrivals.filter(eta__lt="12:00")
    elif eta == "afternoon":
        arrivals = arrivals.filter(eta__gte="12:00")
    elif eta == "none":
        arrivals = arrivals.filter(eta__isnull=True)
    arrivals = list(arrivals)
    departures = list(rep.departures(prop, day))
    in_house = list(rep.in_house(prop))
    logs = list(ShiftLog.objects.filter(property=prop, is_resolved=False).select_related("created_by")[:10])
    wakeups = services.wakeups_due(prop, minutes=12 * 60)
    alerts = []
    for r in list(arrivals) + list(in_house):
        g = r.guest
        if g.is_vip:
            alerts.append((r, "VIP"))
        if g.allergies:
            alerts.append((r, _("Alergias: %(a)s") % {"a": g.allergies}))
        if g.birth_date and (g.birth_date.month, g.birth_date.day) == (day.month, day.day):
            alerts.append((r, _("¡Cumpleaños!")))
        if r.special_requests:
            alerts.append((r, r.special_requests))
        if g.medical_conditions:
            alerts.append((r, _("Salud: %(m)s") % {"m": g.medical_conditions}))
    return render(
        request,
        "frontdesk/panel.html",
        {
            "day": day,
            "tab": tab,
            "eta": eta,
            "arrivals": arrivals,
            "departures": departures,
            "in_house": in_house,
            "logs": logs,
            "wakeups": wakeups,
            "alerts": alerts[:20],
            "counts": {
                "arrivals": len(arrivals),
                "departures": len(departures),
                "in_house": len(in_house),
                "pending_arrivals": sum(1 for r in arrivals if r.status in Reservation.PRE_ARRIVAL_STATUSES),
            },
        },
    )


# --------------------------------------------------------------------------
# Check-in (RF-REC-02/03/04/07)
# --------------------------------------------------------------------------


class CheckInForm(forms.Form):
    room = forms.ModelChoiceField(label=gettext_lazy("Habitación"), queryset=Room.objects.none())
    document_verified = forms.BooleanField(
        label=gettext_lazy("Documento verificado contra el original"), required=False
    )
    validate_non_domiciled = forms.BooleanField(
        label=gettext_lazy("Exonerar IGV: extranjero no domiciliado (pasaporte + TAM)"), required=False
    )
    charge_early = forms.BooleanField(label=gettext_lazy("Cobrar early check-in"), required=False)
    allow_dirty = forms.BooleanField(
        label=gettext_lazy("Ingresar aunque la habitación no esté lista"), required=False
    )
    document_photo = forms.ImageField(label=gettext_lazy("Foto del documento"), required=False)
    signature = forms.CharField(widget=forms.HiddenInput, required=False)


@require_perm("frontdesk.create")
def check_in(request, pk):
    r = get_object_or_404(
        Reservation.objects.select_related("guest", "room", "room_type"), pk=pk, property=request.property
    )
    guest_form = GuestForm(request.POST or None, instance=r.guest, prefix="g")
    form = CheckInForm(request.POST or None, request.FILES or None)
    rooms = free_rooms(r.property, r.arrival, r.departure, room_type=r.room_type, exclude_pk=r.pk)
    if r.room_id:
        rooms = rooms | Room.objects.filter(pk=r.room_id)
    form.fields["room"].queryset = rooms.distinct().order_by("number")
    form.fields["room"].initial = r.room_id
    now = timezone.localtime()
    form.fields["charge_early"].initial = now.time() < r.property.check_in_time
    form.fields["validate_non_domiciled"].initial = r.guest.is_non_domiciled
    if request.method == "POST" and form.is_valid() and guest_form.is_valid():
        before = audit.snapshot(
            r.guest, ["first_name", "last_name", "doc_type", "nationality", "email", "phone"]
        )
        guest = guest_form.save()
        audit.log_changes(guest, before)
        try:
            services.check_in(
                r,
                user=request.user,
                room=form.cleaned_data["room"],
                card_data={
                    "nombre": guest.full_name,
                    "documento": f"{guest.get_doc_type_display()} {guest.masked_doc}",
                    "nacionalidad": str(guest.nationality.name),
                    "tam": guest.tam_number,
                    "ingreso_peru": guest.peru_entry_date.isoformat() if guest.peru_entry_date else "",
                    "procedencia": guest.origin,
                    "destino": guest.next_destination,
                },
                signature=form.cleaned_data["signature"],
                document_verified=form.cleaned_data["document_verified"],
                validate_non_domiciled=form.cleaned_data["validate_non_domiciled"],
                charge_early=form.cleaned_data["charge_early"],
                allow_dirty=form.cleaned_data["allow_dirty"],
            )
            if form.cleaned_data.get("document_photo"):
                card = r.registration_card
                card.document_photo = form.cleaned_data["document_photo"]
                card.save(update_fields=["document_photo"])
            messages.success(request, _("Check-in realizado: habitación %(n)s.") % {"n": r.room.number})
            return redirect("frontdesk:panel")
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    return render(request, "frontdesk/check_in.html", {"r": r, "form": form, "guest_form": guest_form})


@require_perm("frontdesk.create")
def walk_in(request):
    """RF-REC-06: walk-in en menos de 3 pasos (una sola pantalla)."""
    prop = request.property
    day = prop.current_business_date()
    guest_form = QuickGuestForm(request.POST or None, prefix="g")

    class WalkInForm(forms.Form):
        room = forms.ModelChoiceField(
            label=_("Habitación libre"), queryset=free_rooms(prop, day, day + timedelta(days=1))
        )
        rate_plan = forms.ModelChoiceField(
            label=_("Tarifa"), queryset=RatePlan.objects.filter(property=prop, is_active=True)
        )
        nights = forms.IntegerField(label=_("Noches"), min_value=1, max_value=30, initial=1)
        adults = forms.IntegerField(label=_("Adultos"), min_value=1, max_value=6, initial=2)
        signature = forms.CharField(widget=forms.HiddenInput, required=False)

    form = WalkInForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and guest_form.is_valid():
        try:
            guest = guest_form.save()
            r = services.walk_in(
                prop,
                guest=guest,
                room=form.cleaned_data["room"],
                rate_plan=form.cleaned_data["rate_plan"],
                nights=form.cleaned_data["nights"],
                adults=form.cleaned_data["adults"],
                user=request.user,
                signature=form.cleaned_data["signature"],
            )
            messages.success(request, _("Walk-in registrado en la habitación %(n)s.") % {"n": r.room.number})
            return redirect("reservations:reservation_detail", pk=r.pk)
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    return render(request, "frontdesk/walk_in.html", {"form": form, "guest_form": guest_form})


@require_perm("frontdesk.create")
def check_out(request, pk):
    r = get_object_or_404(
        Reservation.objects.select_related("guest", "room"), pk=pk, property=request.property
    )
    if request.method == "POST":
        try:
            services.check_out(
                r,
                user=request.user,
                charge_late=bool(request.POST.get("charge_late")),
                force_balance=bool(request.POST.get("force_balance")),
            )
            messages.success(request, _("Check-out de %(g)s completado.") % {"g": r.guest.full_name})
            return redirect("frontdesk:panel")
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    late = timezone.localtime().time() > r.property.check_out_time
    folios = r.folios.prefetch_related("invoices")
    return render(request, "frontdesk/check_out.html", {"r": r, "folios": folios, "late": late})


class MoveForm(forms.Form):
    room = forms.ModelChoiceField(label=gettext_lazy("Nueva habitación"), queryset=Room.objects.none())
    kind = forms.ChoiceField(label=gettext_lazy("Tipo"), choices=RoomMove.Kind.choices)
    reason = forms.CharField(label=gettext_lazy("Motivo"))
    keep_rate = forms.BooleanField(
        label=gettext_lazy("Mantener la tarifa actual"), required=False, initial=True
    )


@require_perm("frontdesk.edit")
def move_room(request, pk):
    """RF-REC-08: cambio de habitación conservando el folio."""
    r = get_object_or_404(Reservation, pk=pk, property=request.property)
    form = MoveForm(request.POST or None)
    form.fields["room"].queryset = free_rooms(
        r.property, max(r.arrival, r.property.current_business_date()), r.departure, exclude_pk=r.pk
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.move_room(
                r,
                form.cleaned_data["room"],
                kind=form.cleaned_data["kind"],
                reason=form.cleaned_data["reason"],
                user=request.user,
                keep_rate=form.cleaned_data["keep_rate"],
            )
            messages.success(request, _("Habitación cambiada."))
            return redirect("reservations:reservation_detail", pk=r.pk)
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    return render(
        request,
        "core/simple_form.html",
        {
            "form": form,
            "title": _("Cambio de habitación · %(c)s") % {"c": r.code},
            "back": f"/reservas/{r.pk}/",
            "submit": _("Cambiar habitación"),
        },
    )


# --------------------------------------------------------------------------
# Equipaje, novedades y despertador
# --------------------------------------------------------------------------


class LuggageForm(PropertyModelForm):
    class Meta:
        model = LuggageTicket
        fields = ["guest_name", "reservation", "pieces", "location", "description", "expected_pickup"]
        widgets = {"expected_pickup": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reservation"].queryset = (
            self.fields["reservation"]
            .queryset.filter(status__in=["checked_in", "checked_out", "confirmed", "guaranteed"])
            .select_related("guest")
        )


@require_perm("frontdesk.view")
def luggage(request):
    """RF-REC-11: custodia de equipaje con ticket y registro de entrada/salida."""
    prop = request.property
    form = LuggageForm(request.POST or None, property=prop)
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "frontdesk.create"):
            raise PermissionDenied
        if request.POST.get("deliver"):
            t = get_object_or_404(LuggageTicket, pk=request.POST["deliver"], property=prop)
            t.status = LuggageTicket.Status.DELIVERED
            t.delivered_at = timezone.now()
            t.delivered_to = request.POST.get("delivered_to") or t.guest_name
            t.save()
            messages.success(request, _("Equipaje %(n)s entregado.") % {"n": t.number})
            return redirect("frontdesk:luggage")
        if form.is_valid():
            t = services.new_luggage_ticket(prop, **form.cleaned_data)
            messages.success(request, _("Ticket %(n)s emitido.") % {"n": t.number})
            return redirect("frontdesk:luggage")
    tickets = LuggageTicket.objects.filter(property=prop).select_related("reservation")
    show = request.GET.get("estado", "stored")
    if show != "all":
        tickets = tickets.filter(status=show)
    return render(request, "frontdesk/luggage.html", {"form": form, "tickets": tickets[:100], "show": show})


@require_perm("frontdesk.view")
def shift_log(request):
    """RF-REC-12: libro de novedades entre turnos."""
    prop = request.property
    if request.method == "POST":
        if request.POST.get("resolve"):
            ShiftLog.objects.filter(pk=request.POST["resolve"], property=prop).update(is_resolved=True)
        elif request.POST.get("message"):
            ShiftLog.objects.create(
                property=prop,
                message=request.POST["message"],
                priority=request.POST.get("priority", "normal"),
            )
        return redirect("frontdesk:shift_log")
    logs = ShiftLog.objects.filter(property=prop).select_related("created_by")[:100]
    for log in logs:
        log.read_by.add(request.user)
    return render(request, "frontdesk/shift_log.html", {"logs": logs})


@require_perm("frontdesk.view")
def wakeups(request):
    """RF-REC-14: despertador."""
    prop = request.property
    if request.method == "POST":
        if request.POST.get("done"):
            WakeUpCall.objects.filter(pk=request.POST["done"], property=prop).update(
                done=True, done_at=timezone.now()
            )
        else:
            r = get_object_or_404(Reservation, pk=request.POST.get("reservation"), property=prop)
            when = timezone.make_aware(datetime.fromisoformat(request.POST["scheduled_for"]))
            WakeUpCall.objects.create(
                property=prop, reservation=r, scheduled_for=when, notes=request.POST.get("notes", "")
            )
            messages.success(request, _("Despertador programado."))
        return redirect("frontdesk:wakeups")
    calls = WakeUpCall.objects.filter(property=prop, done=False).select_related(
        "reservation__room", "reservation__guest"
    )
    return render(request, "frontdesk/wakeups.html", {"calls": calls, "in_house": rep.in_house(prop)})


# --------------------------------------------------------------------------
# Cierre de día (RF-REC-13)
# --------------------------------------------------------------------------


@require_perm("frontdesk.view")
def night_audit(request):
    prop = request.property
    if request.method == "POST":
        try:
            record = services.run_night_audit(prop, user=request.user)
            messages.success(
                request, _("Día %(d)s cerrado.") % {"d": record.business_date.strftime("%d/%m/%Y")}
            )
            return redirect("frontdesk:night_audit")
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    day = prop.current_business_date()
    preview = {
        "in_house": rep.in_house(prop).filter(departure__gt=day).count(),
        "pending_arrivals": Reservation.objects.filter(
            property=prop, arrival=day, status__in=Reservation.PRE_ARRIVAL_STATUSES
        ).count(),
        "due_out": Reservation.objects.filter(property=prop, status="checked_in", departure__lte=day).count(),
    }
    from apps.folio.models import CashSession

    return render(
        request,
        "frontdesk/night_audit.html",
        {
            "day": day,
            "preview": preview,
            "open_sessions": CashSession.objects.filter(property=prop, status="open").select_related(
                "user", "register"
            ),
            "history": NightAudit.objects.filter(property=prop)[:30],
        },
    )


# --------------------------------------------------------------------------
# Contingencia sin internet (RNF-DIS-03)
# --------------------------------------------------------------------------


@require_perm("frontdesk.view")
def contingency(request, kind, fmt):
    prop = request.property
    day = prop.current_business_date()
    if kind == "llegadas":
        title = _("Llegadas del %(d)s") % {"d": day.strftime("%d/%m/%Y")}
        header = [_("Reserva"), _("Huésped"), _("Tipo"), _("Hab."), _("Noches"), _("ETA"), _("Estado")]
        rows = [
            [
                r.code,
                r.guest.full_name,
                r.room_type.code,
                r.room.number if r.room else "",
                r.nights,
                r.eta.strftime("%H:%M") if r.eta else "",
                r.get_status_display(),
            ]
            for r in rep.arrivals(prop, day)
        ]
    elif kind == "en-casa":
        title = _("Huéspedes en casa %(d)s") % {"d": day.strftime("%d/%m/%Y")}
        header = [_("Hab."), _("Huésped"), _("Documento"), _("País"), _("Salida"), _("Saldo")]
        rows = [
            [
                r.room.number if r.room else "",
                r.guest.full_name,
                r.guest.masked_doc,
                r.guest.nationality.name,
                r.departure.strftime("%d/%m/%Y"),
                r.balance,
            ]
            for r in rep.in_house(prop)
        ]
    elif kind == "libres":
        title = _("Habitaciones disponibles %(d)s") % {"d": day.strftime("%d/%m/%Y")}
        header = [_("Hab."), _("Tipo"), _("Piso"), _("Limpieza")]
        rows = [
            [room.number, room.room_type.name, room.floor, room.get_hk_status_display()]
            for room in rep.free_rooms_today(prop)
        ]
    else:
        raise PermissionDenied
    audit.log(AuditLog.Action.EXPORT, None, changes={"reporte": kind, "formato": fmt}, property=prop)
    from apps.reports.exports import export_table

    return export_table(title, header, rows, fmt, filename=f"{kind}-{day:%Y%m%d}")
