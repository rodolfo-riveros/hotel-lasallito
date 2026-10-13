"""Mantenimiento: activos, órdenes de trabajo y preventivo (RF-MAN-01 a 04, RF-ALM-09)."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}


class Asset(TimeStampedModel, PropertyScopedModel):
    """Equipos y activos fijos con su ubicación (RF-ALM-09, RF-MAN-02)."""

    class Kind(models.TextChoices):
        HEATER = "heater", _("Terma / calentador")
        BOILER = "boiler", _("Caldero")
        ELEVATOR = "elevator", _("Ascensor")
        EXTINGUISHER = "extinguisher", _("Extintor")
        OXYGEN = "oxygen", _("Concentrador de oxígeno")
        FURNITURE = "furniture", _("Mobiliario")
        ELECTRONICS = "electronics", _("Equipo electrónico")
        KITCHEN = "kitchen", _("Equipo de cocina")
        OTHER = "other", _("Otro")

    code = models.CharField(_("código"), max_length=30)
    name = models.CharField(_("nombre"), max_length=150)
    kind = models.CharField(_("tipo"), max_length=15, choices=Kind.choices, default=Kind.OTHER)
    room = models.ForeignKey(
        "rooms.Room",
        verbose_name=_("habitación"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assets",
    )
    area = models.CharField(
        _("área"), max_length=100, blank=True, help_text=_("Si no está en una habitación")
    )
    brand = models.CharField(_("marca / modelo"), max_length=100, blank=True)
    serial = models.CharField(_("serie"), max_length=60, blank=True)
    acquisition_date = models.DateField(_("fecha de compra"), null=True, blank=True)
    value = models.DecimalField(_("valor"), default=Decimal("0"), **MONEY)
    is_active = models.BooleanField(_("en uso"), default=True)

    class Meta:
        verbose_name = _("activo")
        verbose_name_plural = _("activos y equipos")
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def location(self):
        return f"Hab. {self.room.number}" if self.room else self.area


class WorkOrder(TimeStampedModel, PropertyScopedModel):
    """RF-MAN-01: órdenes de trabajo con prioridad, responsable y estado."""

    class Priority(models.TextChoices):
        LOW = "low", _("Baja")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("Alta")
        URGENT = "urgent", _("Urgente")

    class Status(models.TextChoices):
        OPEN = "open", _("Abierta")
        IN_PROGRESS = "in_progress", _("En proceso")
        ON_HOLD = "on_hold", _("En espera de repuesto")
        DONE = "done", _("Terminada")
        CANCELLED = "cancelled", _("Anulada")

    class Source(models.TextChoices):
        HOUSEKEEPING = "housekeeping", _("Housekeeping")
        FRONTDESK = "frontdesk", _("Recepción")
        GUEST = "guest", _("Huésped")
        PREVENTIVE = "preventive", _("Preventivo")
        OTHER = "other", _("Otro")

    number = models.CharField(_("número"), max_length=20)
    title = models.CharField(_("problema"), max_length=150)
    description = models.TextField(_("detalle"), blank=True)
    room = models.ForeignKey(
        "rooms.Room",
        verbose_name=_("habitación"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    asset = models.ForeignKey(
        Asset,
        verbose_name=_("equipo"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    priority = models.CharField(
        _("prioridad"), max_length=10, choices=Priority.choices, default=Priority.NORMAL
    )
    status = models.CharField(_("estado"), max_length=12, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(_("origen"), max_length=15, choices=Source.choices, default=Source.OTHER)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("responsable"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    block_room = models.BooleanField(_("bloquear la habitación mientras esté abierta"), default=False)
    room_block = models.OneToOneField(
        "rooms.RoomBlock", null=True, blank=True, on_delete=models.SET_NULL, related_name="work_order"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(_("solución"), blank=True)
    labor_cost = models.DecimalField(_("mano de obra"), default=Decimal("0"), **MONEY)

    class Meta:
        verbose_name = _("orden de trabajo")
        verbose_name_plural = _("órdenes de trabajo")
        ordering = ["status", "-created_at"]

    def __str__(self):
        return f"{self.number} · {self.title}"

    @property
    def materials_cost(self) -> Decimal:
        return self.parts.aggregate(s=Sum("cost"))["s"] or Decimal("0")

    @property
    def total_cost(self) -> Decimal:
        return self.labor_cost + self.materials_cost


class WorkOrderPart(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="parts")
    item = models.ForeignKey("inventory.Item", verbose_name=_("repuesto"), on_delete=models.PROTECT)
    quantity = models.DecimalField(_("cantidad"), max_digits=12, decimal_places=3)
    cost = models.DecimalField(_("costo"), **MONEY)

    def __str__(self):
        return f"{self.quantity} {self.item}"


class PreventivePlan(TimeStampedModel, PropertyScopedModel):
    """RF-MAN-02: mantenimiento preventivo programado."""

    asset = models.ForeignKey(Asset, verbose_name=_("equipo"), on_delete=models.CASCADE, related_name="plans")
    name = models.CharField(_("tarea"), max_length=150)
    frequency_days = models.PositiveSmallIntegerField(_("cada (días)"), default=30)
    next_due = models.DateField(_("próxima fecha"))
    checklist = models.TextField(_("checklist"), blank=True, help_text=_("Un paso por línea"))
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("responsable"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("plan preventivo")
        verbose_name_plural = _("mantenimiento preventivo")
        ordering = ["next_due"]

    def __str__(self):
        return f"{self.name} · {self.asset}"
