"""Plantillas, mensajes y notificaciones (RF-COMU-01 a RF-COMU-04, RF-RES-11)."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

LANGUAGES = [("es", "Español"), ("en", "English"), ("pt-br", "Português")]


class MessageTemplate(TimeStampedModel, PropertyScopedModel):
    class Event(models.TextChoices):
        CONFIRMATION = "confirmation", _("Confirmación de reserva")
        REMINDER = "reminder", _("Recordatorio 48 h antes")
        WELCOME = "welcome", _("Bienvenida (check-in)")
        THANKS = "thanks", _("Agradecimiento (check-out)")
        SURVEY = "survey", _("Encuesta de satisfacción")
        CANCELLATION = "cancellation", _("Cancelación")
        INVOICE = "invoice", _("Envío de comprobante")

    class Channel(models.TextChoices):
        EMAIL = "email", _("Correo")
        WHATSAPP = "whatsapp", _("WhatsApp")

    event = models.CharField(_("evento"), max_length=20, choices=Event.choices)
    channel = models.CharField(_("canal"), max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    language = models.CharField(_("idioma"), max_length=5, choices=LANGUAGES, default="es")
    subject = models.CharField(_("asunto"), max_length=200, blank=True)
    body = models.TextField(
        _("texto"),
        help_text=_(
            "Variables: {{ guest.first_name }}, {{ reservation.code }}, {{ reservation.arrival }}, "
            "{{ property.name }}, {{ portal_url }}, {{ survey_url }}"
        ),
    )
    whatsapp_template_name = models.CharField(_("plantilla aprobada en WhatsApp"), max_length=100, blank=True)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("plantilla de mensaje")
        verbose_name_plural = _("plantillas de mensajes")
        ordering = ["event", "channel", "language"]
        constraints = [
            models.UniqueConstraint(fields=["property", "event", "channel", "language"], name="uniq_template")
        ]

    def __str__(self):
        return f"{self.get_event_display()} · {self.get_channel_display()} · {self.language}"


class AutomationSetting(PropertyScopedModel):
    """RF-COMU-02: mensajes automáticos por evento, con opción de apagarlos."""

    event = models.CharField(_("evento"), max_length=20, choices=MessageTemplate.Event.choices)
    email_enabled = models.BooleanField(_("enviar correo"), default=True)
    whatsapp_enabled = models.BooleanField(_("enviar WhatsApp"), default=False)

    class Meta:
        verbose_name = _("envío automático")
        verbose_name_plural = _("envíos automáticos")
        constraints = [models.UniqueConstraint(fields=["property", "event"], name="uniq_automation_event")]

    def __str__(self):
        return self.get_event_display()


class Message(TimeStampedModel, PropertyScopedModel):
    """RF-COMU-03: bandeja de mensajes con el huésped dentro de la reserva."""

    class Direction(models.TextChoices):
        OUT = "out", _("Enviado")
        IN = "in", _("Recibido")

    class Status(models.TextChoices):
        QUEUED = "queued", _("En cola")
        SENT = "sent", _("Enviado")
        FAILED = "failed", _("Falló")
        RECEIVED = "received", _("Recibido")

    reservation = models.ForeignKey(
        "reservations.Reservation", null=True, blank=True, on_delete=models.CASCADE, related_name="messages"
    )
    guest = models.ForeignKey(
        "guests.Guest", null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    event = models.CharField(_("evento"), max_length=20, blank=True)
    channel = models.CharField(_("canal"), max_length=10, choices=MessageTemplate.Channel.choices)
    direction = models.CharField(
        _("dirección"), max_length=3, choices=Direction.choices, default=Direction.OUT
    )
    to = models.CharField(_("destinatario"), max_length=200)
    subject = models.CharField(_("asunto"), max_length=200, blank=True)
    body = models.TextField(_("texto"))
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.QUEUED)
    error = models.CharField(_("error"), max_length=255, blank=True)
    sent_at = models.DateTimeField(_("enviado el"), null=True, blank=True)

    class Meta:
        verbose_name = _("mensaje")
        verbose_name_plural = _("mensajes")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_channel_display()} → {self.to}: {self.subject or self.body[:40]}"


class Notification(models.Model):
    """RF-COMU-04: notificaciones internas al personal."""

    property = models.ForeignKey("core.Property", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    role_code = models.CharField(
        max_length=40, blank=True, help_text=_("Para todos los usuarios de ese rol.")
    )
    title = models.CharField(_("título"), max_length=150)
    body = models.CharField(_("detalle"), max_length=300, blank=True)
    url = models.CharField(max_length=200, blank=True)
    level = models.CharField(max_length=10, default="info")
    created_at = models.DateTimeField(auto_now_add=True)
    read_by = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
