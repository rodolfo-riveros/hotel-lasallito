from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm

from . import services
from .models import AutomationSetting, Message, MessageTemplate, Notification


class TemplateForm(PropertyModelForm):
    class Meta:
        model = MessageTemplate
        exclude = ["property", "created_by", "updated_by"]
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}


template_crud = Crud(
    model=MessageTemplate,
    module="comms",
    form_class=TemplateForm,
    columns=[
        (gettext_lazy("Evento"), "event"),
        (gettext_lazy("Canal"), "channel"),
        (gettext_lazy("Idioma"), "language"),
        (gettext_lazy("Asunto"), "subject"),
        (gettext_lazy("Activa"), "is_active"),
    ],
    filters=["event", "channel", "language"],
    help_text=gettext_lazy("Plantillas en español, inglés y portugués (RF-COMU-01)."),
)


@require_perm("comms.view")
def inbox(request):
    """RF-COMU-03: bandeja de mensajes enviados y recibidos."""
    qs = Message.objects.filter(property=request.property).select_related("reservation", "guest")
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return render(
        request, "comms/inbox.html", {"messages_list": qs[:200], "statuses": Message.Status.choices}
    )


@require_perm("comms.view")
def automations(request):
    """RF-COMU-02: mensajes automáticos por evento, con opción de apagarlos."""
    prop = request.property
    if request.method == "POST" and request.user.has_pms_perm(prop, "comms.edit"):
        for event, _label in MessageTemplate.Event.choices:
            AutomationSetting.objects.update_or_create(
                property=prop,
                event=event,
                defaults={
                    "email_enabled": bool(request.POST.get(f"email-{event}")),
                    "whatsapp_enabled": bool(request.POST.get(f"wa-{event}")),
                },
            )
        messages.success(request, _("Envíos automáticos actualizados."))
        return redirect("comms:automations")
    current = {a.event: a for a in AutomationSetting.objects.filter(property=prop)}
    rows = [
        {
            "event": e,
            "label": label,
            "email": current[e].email_enabled if e in current else True,
            "wa": current[e].whatsapp_enabled if e in current else False,
        }
        for e, label in MessageTemplate.Event.choices
    ]
    return render(request, "comms/automations.html", {"rows": rows})


@require_perm("comms.create")
def compose(request, reservation_pk):
    from apps.reservations.models import Reservation

    r = get_object_or_404(Reservation, pk=reservation_pk, property=request.property)
    if request.method == "POST":
        channel = request.POST.get("channel", "email")
        to = r.guest.email if channel == "email" else r.guest.phone
        msg = services.send_message(
            r.property,
            channel,
            to,
            request.POST.get("subject", ""),
            request.POST.get("body", ""),
            reservation=r,
        )
        messages.success(request, _("Mensaje %(s)s.") % {"s": msg.get_status_display().lower()})
    return redirect("reservations:reservation_detail", pk=r.pk)


@require_perm("dashboard.view")
def notifications(request):
    """RF-COMU-04: notificaciones internas al personal."""
    qs = services.notifications_for(request.user, request.property)[:50]
    if request.method == "POST":
        for n in services.notifications_for(request.user, request.property).exclude(read_by=request.user):
            n.read_by.add(request.user)
        return redirect("comms:notifications")
    return render(request, "comms/notifications.html", {"items": qs})


@require_POST
@require_perm("dashboard.view")
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, property=request.property)
    n.read_by.add(request.user)
    return redirect(n.url or "comms:notifications")
