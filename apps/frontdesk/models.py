"""Recepción: ficha de registro, equipaje, novedades, despertador y cierre de día (RF-REC)."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class RegistrationCard(TimeStampedModel):
    """RF-REC-02/03: ficha de registro firmada digitalmente."""

    reservation = models.OneToOneField(
        "reservations.Reservation", on_delete=models.CASCADE, related_name="registration_card"
    )
    data = models.JSONField(_("datos registrados"), default=dict)
    signature = models.TextField(_("firma (imagen)"), blank=True)
    signed_at = models.DateTimeField(_("firmada el"), null=True, blank=True)
    document_photo = models.ImageField(_("foto del documento"), upload_to="frontdesk/documents/", blank=True)
    document_verified = models.BooleanField(_("documento verificado"), default=False)
    terms_accepted = models.BooleanField(_("acepta normas del hotel y Ley 29733"), default=False)

    class Meta:
        verbose_name = _("ficha de registro")
        verbose_name_plural = _("fichas de registro")

    def __str__(self):
        return f"Ficha {self.reservation.code}"


class RoomMove(TimeStampedModel):
    """RF-REC-08: historial de cambios de habitación (upgrade, downgrade, reubicación)."""

    class Kind(models.TextChoices):
        UPGRADE = "upgrade", _("Upgrade")
        DOWNGRADE = "downgrade", _("Downgrade")
        RELOCATION = "relocation", _("Reubicación")

    reservation = models.ForeignKey(
        "reservations.Reservation", on_delete=models.CASCADE, related_name="room_moves"
    )
    from_room = models.ForeignKey("rooms.Room", on_delete=models.PROTECT, related_name="+")
    to_room = models.ForeignKey("rooms.Room", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(_("tipo"), max_length=12, choices=Kind.choices)
    reason = models.CharField(_("motivo"), max_length=255)
    keep_rate = models.BooleanField(_("mantener tarifa"), default=True)

    class Meta:
        verbose_name = _("cambio de habitación")
        verbose_name_plural = _("cambios de habitación")

    def __str__(self):
        return f"{self.from_room.number} → {self.to_room.number}"


class LuggageTicket(TimeStampedModel, PropertyScopedModel):
    """RF-REC-11: custodia de equipaje (muy usada antes de ir a Machu Picchu)."""

    class Status(models.TextChoices):
        STORED = "stored", _("En custodia")
        DELIVERED = "delivered", _("Entregado")

    number = models.CharField(_("ticket"), max_length=20)
    guest_name = models.CharField(_("huésped"), max_length=150)
    reservation = models.ForeignKey(
        "reservations.Reservation", null=True, blank=True, on_delete=models.SET_NULL, related_name="luggage"
    )
    pieces = models.PositiveSmallIntegerField(_("bultos"), default=1)
    location = models.CharField(_("ubicación"), max_length=100, blank=True)
    description = models.CharField(_("descripción"), max_length=255, blank=True)
    expected_pickup = models.DateField(_("recojo previsto"), null=True, blank=True)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.STORED)
    delivered_at = models.DateTimeField(_("entregado el"), null=True, blank=True)
    delivered_to = models.CharField(_("entregado a"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("ticket de equipaje")
        verbose_name_plural = _("custodia de equipaje")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} · {self.guest_name}"


class ShiftLog(TimeStampedModel, PropertyScopedModel):
    """RF-REC-12: libro de novedades y mensajes entre turnos."""

    class Priority(models.TextChoices):
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("Importante")

    message = models.TextField(_("novedad"))
    priority = models.CharField(
        _("prioridad"), max_length=10, choices=Priority.choices, default=Priority.NORMAL
    )
    reservation = models.ForeignKey(
        "reservations.Reservation", null=True, blank=True, on_delete=models.SET_NULL
    )
    is_resolved = models.BooleanField(_("resuelta"), default=False)
    read_by = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")

    class Meta:
        verbose_name = _("novedad de turno")
        verbose_name_plural = _("libro de novedades")
        ordering = ["is_resolved", "-created_at"]

    def __str__(self):
        return self.message[:60]


class WakeUpCall(TimeStampedModel, PropertyScopedModel):
    """RF-REC-14: despertador y llamadas pendientes."""

    reservation = models.ForeignKey(
        "reservations.Reservation", on_delete=models.CASCADE, related_name="wakeups"
    )
    scheduled_for = models.DateTimeField(_("fecha y hora"))
    notes = models.CharField(_("notas"), max_length=150, blank=True, help_text=_("Ej. tren a Machu Picchu"))
    done = models.BooleanField(_("realizada"), default=False)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("despertador")
        verbose_name_plural = _("despertadores")
        ordering = ["scheduled_for"]

    def __str__(self):
        return f"{self.reservation.room or '-'} {self.scheduled_for:%d/%m %H:%M}"


class NightAudit(TimeStampedModel, PropertyScopedModel):
    """RF-REC-13: cierre de día."""

    business_date = models.DateField(_("fecha cerrada"))
    summary = models.JSONField(_("resumen"), default=dict)
    warnings = models.JSONField(_("advertencias"), default=list)

    class Meta:
        verbose_name = _("cierre de día")
        verbose_name_plural = _("cierres de día")
        ordering = ["-business_date"]
        constraints = [models.UniqueConstraint(fields=["property", "business_date"], name="uniq_night_audit")]

    def __str__(self):
        return f"Cierre {self.business_date:%d/%m/%Y}"
