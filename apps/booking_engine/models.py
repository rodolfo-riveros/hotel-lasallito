"""Motor de reservas web: solicitudes de grupo (RF-WEB-05)."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class GroupRequest(TimeStampedModel, PropertyScopedModel):
    """RF-WEB-05: pedido de cotización de grupo desde la web."""

    class Status(models.TextChoices):
        NEW = "new", _("Nueva")
        QUOTED = "quoted", _("Cotizada")
        WON = "won", _("Confirmada")
        LOST = "lost", _("Perdida")

    name = models.CharField(_("contacto"), max_length=150)
    company = models.CharField(_("empresa / agencia"), max_length=150, blank=True)
    email = models.EmailField(_("correo"))
    phone = models.CharField(_("teléfono / WhatsApp"), max_length=30, blank=True)
    arrival = models.DateField(_("llegada"))
    departure = models.DateField(_("salida"))
    rooms = models.PositiveSmallIntegerField(_("habitaciones"), default=5)
    pax = models.PositiveSmallIntegerField(_("personas"), default=10)
    notes = models.TextField(_("detalles"), blank=True)
    language = models.CharField(_("idioma"), max_length=5, default="es")
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.NEW)

    class Meta:
        verbose_name = _("solicitud de grupo")
        verbose_name_plural = _("solicitudes de grupo")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} · {self.arrival:%d/%m/%Y} · {self.rooms} hab."
