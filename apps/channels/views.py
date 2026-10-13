from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.rates.models import RatePlan
from apps.rooms.models import RoomType

from . import services
from .models import Channel, ChannelInventory, RateMapping, RoomMapping, SyncLog


class ChannelForm(PropertyModelForm):
    class Meta:
        model = Channel
        fields = ["code", "name", "hotel_id", "commission_percent", "company", "is_active"]


channel_crud = Crud(
    model=Channel,
    module="channels",
    form_class=ChannelForm,
    columns=[
        (gettext_lazy("Canal"), "name"),
        (gettext_lazy("Código"), "code"),
        (gettext_lazy("Comisión %"), "commission_percent"),
        (gettext_lazy("Conectado"), "is_active"),
        (gettext_lazy("Última sinc."), "last_sync_at"),
    ],
)


@require_perm("channels.view")
def panel(request):
    """RF-CHA-01/04: estado de los canales, errores y reintentos."""
    prop = request.property
    channels = Channel.objects.filter(property=prop).prefetch_related(
        "room_mappings__room_type", "rate_mappings"
    )
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "channels.edit"):
            raise PermissionDenied
        action = request.POST.get("action")
        if action == "push":
            logs = services.push_all(prop)
            ok = sum(1 for log in logs if log.status == "ok")
            messages.success(request, _("Publicado en %(ok)s de %(n)s canales.") % {"ok": ok, "n": len(logs)})
        elif action == "retry":
            log = get_object_or_404(SyncLog, pk=request.POST.get("log"), property=prop)
            services.retry(log)
            messages.info(request, log.message)
        return redirect("channels:panel")
    today = prop.current_business_date()
    return render(
        request,
        "channels/panel.html",
        {
            "channels": channels,
            "errors": SyncLog.objects.filter(property=prop, status="error").select_related("channel")[:20],
            "logs": SyncLog.objects.filter(property=prop).select_related("channel")[:30],
            "dirty": services.is_dirty(prop),
            "commissions": services.commission_report(prop, today.replace(day=1), today + timedelta(days=60)),
        },
    )


@require_perm("channels.edit")
def mappings(request, pk):
    """RF-CHA-03: mapeo de tipos de habitación y planes por canal."""
    channel = get_object_or_404(Channel, pk=pk, property=request.property)
    types = RoomType.objects.filter(property=request.property, is_active=True)
    plans = RatePlan.objects.filter(property=request.property, is_active=True)
    if request.method == "POST":
        for rt in types:
            code = request.POST.get(f"room-{rt.pk}", "").strip()
            if code:
                RoomMapping.objects.update_or_create(
                    channel=channel, room_type=rt, defaults={"external_code": code}
                )
            else:
                RoomMapping.objects.filter(channel=channel, room_type=rt).delete()
        for p in plans:
            code = request.POST.get(f"rate-{p.pk}", "").strip()
            if code:
                RateMapping.objects.update_or_create(
                    channel=channel,
                    rate_plan=p,
                    defaults={
                        "external_code": code,
                        "markup_percent": request.POST.get(f"markup-{p.pk}") or 0,
                    },
                )
            else:
                RateMapping.objects.filter(channel=channel, rate_plan=p).delete()
        messages.success(request, _("Mapeo guardado."))
        return redirect("channels:panel")
    rooms = {m.room_type_id: m.external_code for m in channel.room_mappings.all()}
    rates = {m.rate_plan_id: m for m in channel.rate_mappings.all()}
    return render(
        request,
        "channels/mappings.html",
        {
            "channel": channel,
            "types": [{"rt": rt, "code": rooms.get(rt.pk, "")} for rt in types],
            "plans": [{"p": p, "m": rates.get(p.pk)} for p in plans],
        },
    )


@require_perm("channels.view")
def published(request, pk):
    """Lo que el canal tiene publicado (vista del extranet simulado)."""
    channel = get_object_or_404(Channel, pk=pk, property=request.property)
    start = request.property.current_business_date()
    days = [start + timedelta(days=i) for i in range(14)]
    inv = {
        (i.room_type_id, i.date): i for i in ChannelInventory.objects.filter(channel=channel, date__in=days)
    }
    rows = [
        {"rt": m.room_type, "cells": [inv.get((m.room_type_id, d)) for d in days]}
        for m in channel.room_mappings.select_related("room_type")
    ]
    return render(request, "channels/published.html", {"channel": channel, "days": days, "rows": rows})


class InboundForm(forms.Form):
    channel = forms.ModelChoiceField(label=gettext_lazy("Canal"), queryset=Channel.objects.none())
    room_code = forms.CharField(label=gettext_lazy("Código de habitación en el canal"))
    arrival = forms.DateField(label=gettext_lazy("Llegada"), widget=forms.DateInput(attrs={"type": "date"}))
    departure = forms.DateField(label=gettext_lazy("Salida"), widget=forms.DateInput(attrs={"type": "date"}))
    adults = forms.IntegerField(label=gettext_lazy("Adultos"), initial=2, min_value=1)
    first_name = forms.CharField(label=gettext_lazy("Nombres"))
    last_name = forms.CharField(label=gettext_lazy("Apellidos"))
    email = forms.EmailField(label=gettext_lazy("Correo"), required=False)
    country = forms.CharField(label=gettext_lazy("País (código)"), initial="US", max_length=2)
    total = forms.DecimalField(label=gettext_lazy("Total cobrado por el canal (opcional)"), required=False)
    external_id = forms.CharField(label=gettext_lazy("N.° de reserva del canal"))
    cancel = forms.BooleanField(label=gettext_lazy("Es una cancelación"), required=False)


@require_perm("channels.edit")
def simulate_inbound(request):
    """Entorno de pruebas: simula que llega (o se cancela) una reserva desde un canal."""
    form = InboundForm(
        request.POST or None,
        initial={
            "arrival": request.property.current_business_date() + timedelta(days=5),
            "departure": request.property.current_business_date() + timedelta(days=7),
            "external_id": f"BK{date.today():%m%d}{SyncLog.objects.count() + 1:04d}",
        },
    )
    form.fields["channel"].queryset = Channel.objects.filter(property=request.property)
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        payload = {
            "external_id": cd["external_id"],
            "room_code": cd["room_code"],
            "arrival": cd["arrival"].isoformat(),
            "departure": cd["departure"].isoformat(),
            "adults": cd["adults"],
            "children": 0,
            "total": str(cd["total"]) if cd["total"] else None,
            "status": "cancelled" if cd["cancel"] else "new",
            "guest": {
                "first_name": cd["first_name"],
                "last_name": cd["last_name"],
                "email": cd["email"],
                "country": cd["country"].upper(),
                "language": "en",
            },
        }
        r = services.receive_reservation(cd["channel"], payload)
        if r is None:
            messages.error(request, _("La reserva no ingresó. Revise el panel de errores."))
            return redirect("channels:panel")
        services.push_all(request.property)
        messages.success(
            request,
            _("Reserva %(c)s procesada y disponibilidad publicada en todos los canales.") % {"c": r.code},
        )
        return redirect("reservations:reservation_detail", pk=r.pk)
    return render(
        request,
        "core/simple_form.html",
        {
            "form": form,
            "title": _("Simular reserva entrante de un canal"),
            "back": "/canales/",
            "subtitle": _("Así llegan las reservas de Booking o Expedia por el channel manager (RF-CHA-02)."),
            "submit": _("Enviar al PMS"),
        },
    )
