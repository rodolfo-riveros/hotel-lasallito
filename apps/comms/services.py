"""Envío de correos y WhatsApp por evento (RF-COMU-01/02, RF-RES-11, RF-WEB-05).

Los canales van detrás de adaptadores: el correo usa el backend de Django
(EMAIL_URL) y WhatsApp la API de WhatsApp Business (WHATSAPP_TOKEN y
WHATSAPP_PHONE_ID). Sin credenciales, WhatsApp queda registrado como enviado
en modo prueba, sin salir del sistema.
"""

import json
import logging
import urllib.request

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template import Context, Template
from django.utils import timezone, translation

from .models import AutomationSetting, Message, MessageTemplate, Notification

log = logging.getLogger(__name__)


def site_url() -> str:
    return getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")


def portal_url(reservation) -> str:
    return f"{site_url()}/portal/{reservation.portal_token}/"


def _lang(language: str) -> str:
    return language if language in ("es", "en", "pt-br") else "es"


def get_template(property_obj, event, channel, language):
    qs = MessageTemplate.objects.filter(property=property_obj, event=event, channel=channel, is_active=True)
    return qs.filter(language=_lang(language)).first() or qs.filter(language="es").first()


def render_text(text: str, context: dict) -> str:
    return Template(text).render(Context(context, autoescape=False))


def context_for(reservation, **extra) -> dict:
    return {
        "guest": reservation.guest,
        "reservation": reservation,
        "property": reservation.property,
        "portal_url": portal_url(reservation),
        "survey_url": f"{portal_url(reservation)}encuesta/",
        **extra,
    }


# --------------------------------------------------------------------------
# Adaptadores
# --------------------------------------------------------------------------


class EmailAdapter:
    def send(self, message: Message, attachments=None, html=None):
        email = EmailMultiAlternatives(
            message.subject, message.body, settings.DEFAULT_FROM_EMAIL, [message.to]
        )
        if html:
            email.attach_alternative(html, "text/html")
        for name, content, mimetype in attachments or []:
            email.attach(name, content, mimetype)
        email.send()


class WhatsAppAdapter:
    """WhatsApp Business Cloud API (graph.facebook.com)."""

    def send(self, message: Message, attachments=None, html=None):
        token = getattr(settings, "WHATSAPP_TOKEN", "")
        phone_id = getattr(settings, "WHATSAPP_PHONE_ID", "")
        if not token or not phone_id:
            message.error = "Modo prueba: WhatsApp sin credenciales configuradas"
            return
        to = "".join(c for c in message.to if c.isdigit())
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message.body}}
        req = urllib.request.Request(  # noqa: S310 - URL fija de la API oficial
            f"https://graph.facebook.com/v20.0/{phone_id}/messages",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            resp.read()


ADAPTERS = {"email": EmailAdapter, "whatsapp": WhatsAppAdapter}


def deliver(message: Message, attachments=None, html=None) -> Message:
    try:
        ADAPTERS[message.channel]().send(message, attachments=attachments, html=html)
        message.status = Message.Status.SENT
        message.sent_at = timezone.now()
    except Exception as exc:  # noqa: BLE001 - se registra el fallo en el mensaje
        log.exception("Fallo al enviar mensaje %s", message.pk)
        message.status = Message.Status.FAILED
        message.error = str(exc)[:255]
    message.save()
    return message


def send_message(
    property_obj,
    channel,
    to,
    subject,
    body,
    *,
    reservation=None,
    guest=None,
    event="",
    attachments=None,
    html=None,
):
    message = Message.objects.create(
        property=property_obj,
        reservation=reservation,
        guest=guest or (reservation.guest if reservation else None),
        event=event,
        channel=channel,
        to=to,
        subject=subject,
        body=body,
    )
    return deliver(message, attachments=attachments, html=html)


def is_enabled(property_obj, event, channel) -> bool:
    setting = AutomationSetting.objects.filter(property=property_obj, event=event).first()
    if setting is None:
        return channel == "email"
    return setting.email_enabled if channel == "email" else setting.whatsapp_enabled


def send_event(event: str, reservation, *, force=False, attachments=None) -> list[Message]:
    """Envía los mensajes de un evento en el idioma del huésped."""
    sent = []
    guest = reservation.guest
    language = _lang(reservation.language or guest.language)
    for channel, to in (("email", guest.email), ("whatsapp", guest.phone)):
        if not to or not (force or is_enabled(reservation.property, event, channel)):
            continue
        template = get_template(reservation.property, event, channel, language)
        if template is None:
            continue
        with translation.override(language):
            ctx = context_for(reservation)
            subject = render_text(template.subject, ctx)
            body = render_text(template.body, ctx)
            files = list(attachments or [])
            if event == "confirmation" and channel == "email":
                files.append(_confirmation_pdf(reservation, language))
        sent.append(
            send_message(
                reservation.property,
                channel,
                to,
                subject,
                body,
                reservation=reservation,
                event=event,
                attachments=files if channel == "email" else None,
            )
        )
    return sent


def _confirmation_pdf(reservation, language):
    from apps.core.pdf import render_pdf

    with translation.override(language):
        pdf = render_pdf(
            "comms/confirmation_pdf.html",
            {"r": reservation, "property": reservation.property, "portal_url": portal_url(reservation)},
        )
    return (f"reserva-{reservation.code}.pdf", pdf, "application/pdf")


def send_reminders(property_obj, today=None) -> int:
    """RF-COMU-02: recordatorio 48 horas antes de la llegada (se ejecuta a diario)."""
    from datetime import timedelta

    from apps.reservations.models import Reservation

    today = today or timezone.localdate()
    target = today + timedelta(days=2)
    count = 0
    for r in Reservation.objects.filter(
        property=property_obj, arrival=target, status__in=Reservation.PRE_ARRIVAL_STATUSES
    ).select_related("guest", "property"):
        if Message.objects.filter(reservation=r, event="reminder").exists():
            continue
        count += len(send_event("reminder", r))
    return count


# --------------------------------------------------------------------------
# Notificaciones internas
# --------------------------------------------------------------------------


def notify_role(property_obj, role_code, title, body="", url="", level="info"):
    return Notification.objects.create(
        property=property_obj,
        role_code=role_code,
        title=str(title)[:150],
        body=str(body)[:300],
        url=url,
        level=level,
    )


def notify_user(user, property_obj, title, body="", url="", level="info"):
    return Notification.objects.create(
        property=property_obj, user=user, title=str(title)[:150], body=str(body)[:300], url=url, level=level
    )


def notifications_for(user, property_obj):
    if property_obj is None:
        return Notification.objects.none()
    role = user.role_for(property_obj)
    cond = Q(user=user)
    if role:
        cond |= Q(role_code=role.code, user__isnull=True)
    if user.is_superuser:
        cond |= Q(role_code__in=["admin", "manager"])
    return Notification.objects.filter(cond, property=property_obj)


def unread_count(user, property_obj) -> int:
    return notifications_for(user, property_obj).exclude(read_by=user).count()


def store_inbound_whatsapp(payload: dict) -> int:
    """Guarda mensajes entrantes de WhatsApp y los asocia al huésped en casa con ese número."""
    from apps.guests.models import Guest
    from apps.reservations.models import Reservation

    count = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                phone = "+" + "".join(c for c in msg.get("from", "") if c.isdigit())
                body = (msg.get("text") or {}).get("body", "")
                guest = Guest.objects.filter(phone__endswith=phone[-9:]).first() if len(phone) > 8 else None
                reservation = (
                    Reservation.objects.filter(guest=guest).order_by("-arrival").first() if guest else None
                )
                if reservation is None:
                    continue
                Message.objects.create(
                    property=reservation.property,
                    reservation=reservation,
                    guest=guest,
                    channel="whatsapp",
                    direction=Message.Direction.IN,
                    to=phone,
                    body=body,
                    status=Message.Status.RECEIVED,
                    sent_at=timezone.now(),
                )
                notify_role(
                    reservation.property,
                    "receptionist",
                    f"WhatsApp de {guest}",
                    body[:200],
                    url=f"/reservas/{reservation.pk}/",
                )
                count += 1
    return count
