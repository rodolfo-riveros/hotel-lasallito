"""Channel manager: canales, mapeos y bitácora de sincronización (RF-CHA-01 a 04)."""

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class Channel(TimeStampedModel, PropertyScopedModel):
    class Code(models.TextChoices):
        BOOKING = "booking", "Booking.com"
        EXPEDIA = "expedia", "Expedia"
        AIRBNB = "airbnb", "Airbnb"
        AGENCY = "agency", _("Agencia en línea")

    code = models.CharField(_("canal"), max_length=12, choices=Code.choices)
    name = models.CharField(_("nombre"), max_length=100)
    hotel_id = models.CharField(_("ID del hotel en el canal"), max_length=60, blank=True)
    commission_percent = models.DecimalField(
        _("comisión (%)"), max_digits=5, decimal_places=2, default=Decimal("15")
    )
    company = models.ForeignKey(
        "guests.Company",
        verbose_name=_("empresa (para facturar comisión)"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    is_active = models.BooleanField(_("conectado"), default=True)
    last_sync_at = models.DateTimeField(_("última sincronización"), null=True, blank=True)

    class Meta:
        verbose_name = _("canal")
        verbose_name_plural = _("canales")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_channel_code")]

    def __str__(self):
        return self.name


class RoomMapping(models.Model):
    """RF-CHA-03: tipo de habitación del PMS ↔ código en el canal."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="room_mappings")
    room_type = models.ForeignKey(
        "rooms.RoomType", verbose_name=_("tipo de habitación"), on_delete=models.CASCADE
    )
    external_code = models.CharField(_("código en el canal"), max_length=60)

    class Meta:
        verbose_name = _("mapeo de habitación")
        constraints = [models.UniqueConstraint(fields=["channel", "room_type"], name="uniq_room_mapping")]

    def __str__(self):
        return f"{self.room_type} → {self.external_code}"


class RateMapping(models.Model):
    """RF-CHA-03: plan de tarifa del PMS ↔ código en el canal."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="rate_mappings")
    rate_plan = models.ForeignKey(
        "rates.RatePlan", verbose_name=_("plan de tarifa"), on_delete=models.CASCADE
    )
    external_code = models.CharField(_("código en el canal"), max_length=60)
    markup_percent = models.DecimalField(
        _("recargo para el canal (%)"), max_digits=5, decimal_places=2, default=Decimal("0")
    )

    class Meta:
        verbose_name = _("mapeo de tarifa")
        constraints = [models.UniqueConstraint(fields=["channel", "rate_plan"], name="uniq_rate_mapping")]

    def __str__(self):
        return f"{self.rate_plan} → {self.external_code}"


class SyncLog(TimeStampedModel, PropertyScopedModel):
    """RF-CHA-04: cada envío o recepción, con su resultado y reintentos."""

    class Direction(models.TextChoices):
        PUSH = "push", _("Envío (disponibilidad y tarifas)")
        PULL = "pull", _("Recepción (reservas)")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pendiente")
        OK = "ok", _("Correcto")
        ERROR = "error", _("Error")

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="logs")
    direction = models.CharField(_("dirección"), max_length=5, choices=Direction.choices)
    status = models.CharField(_("estado"), max_length=8, choices=Status.choices, default=Status.PENDING)
    date_from = models.DateField(_("desde"), null=True, blank=True)
    date_to = models.DateField(_("hasta"), null=True, blank=True)
    payload = models.JSONField(_("datos"), default=dict, blank=True)
    message = models.CharField(_("mensaje"), max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(_("intentos"), default=0)

    class Meta:
        verbose_name = _("sincronización")
        verbose_name_plural = _("sincronizaciones")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} {self.get_direction_display()} {self.get_status_display()}"


class ChannelInventory(models.Model):
    """Lo último que el canal tiene publicado por tipo y día (para el simulador y la auditoría)."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="inventory")
    room_type = models.ForeignKey("rooms.RoomType", on_delete=models.CASCADE)
    date = models.DateField()
    available = models.IntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["channel", "room_type", "date"], name="uniq_channel_inv")
        ]

    def __str__(self):
        return f"{self.channel} {self.room_type} {self.date}: {self.available}"
