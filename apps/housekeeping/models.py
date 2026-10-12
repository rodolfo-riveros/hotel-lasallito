"""Housekeeping (RF-HK-01 a RF-HK-08)."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

CHECKLISTS = {
    "departure": [
        "Retirar lencería y toallas usadas",
        "Cambiar sábanas y fundas",
        "Limpiar y desinfectar baño",
        "Reponer amenities",
        "Revisar minibar",
        "Revisar inventario de la habitación",
        "Aspirar y trapear",
        "Revisar calefacción y balón de oxígeno",
    ],
    "stayover": [
        "Tender la cama",
        "Cambiar toallas si se solicitó",
        "Limpiar baño",
        "Reponer amenities y té de coca",
        "Vaciar papeleras",
    ],
    "deep": [
        "Mover muebles y limpiar detrás",
        "Lavar cortinas",
        "Limpiar ventanas por dentro y fuera",
        "Desinfectar colchón",
        "Revisar instalaciones eléctricas y de agua",
    ],
    "touchup": ["Revisión rápida antes de la llegada", "Ajustar temperatura"],
}


class CleaningTask(TimeStampedModel, PropertyScopedModel):
    class Kind(models.TextChoices):
        DEPARTURE = "departure", _("Salida")
        STAYOVER = "stayover", _("Estadía")
        DEEP = "deep", _("Profunda")
        TOUCHUP = "touchup", _("Repaso")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pendiente")
        IN_PROGRESS = "in_progress", _("En limpieza")
        DONE = "done", _("Terminada")
        INSPECTED = "inspected", _("Aprobada")
        REJECTED = "rejected", _("Rechazada")

    CREDITS = {"departure": 2, "stayover": 1, "deep": 4, "touchup": 1}

    room = models.ForeignKey(
        "rooms.Room", verbose_name=_("habitación"), on_delete=models.CASCADE, related_name="tasks"
    )
    date = models.DateField(_("fecha"), db_index=True)
    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices)
    priority = models.PositiveSmallIntegerField(_("prioridad"), default=5, help_text=_("1 = más urgente"))
    priority_reason = models.CharField(_("motivo de prioridad"), max_length=100, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("asignada a"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cleaning_tasks",
    )
    status = models.CharField(_("estado"), max_length=12, choices=Status.choices, default=Status.PENDING)
    checklist = models.JSONField(_("checklist"), default=dict, blank=True)
    started_at = models.DateTimeField(_("inicio"), null=True, blank=True)
    finished_at = models.DateTimeField(_("fin"), null=True, blank=True)
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    inspected_at = models.DateTimeField(null=True, blank=True)
    inspection_notes = models.CharField(_("observaciones de inspección"), max_length=255, blank=True)
    inspection_photo = models.ImageField(
        _("foto de inspección"), upload_to="housekeeping/inspections/", blank=True
    )
    notes = models.CharField(_("notas"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("tarea de limpieza")
        verbose_name_plural = _("tareas de limpieza")
        ordering = ["date", "priority", "room__floor", "room__number"]
        constraints = [
            models.UniqueConstraint(fields=["room", "date", "kind"], name="uniq_task_room_day_kind"),
        ]

    def __str__(self):
        return f"{self.room.number} · {self.get_kind_display()} · {self.date:%d/%m}"

    @property
    def minutes(self):
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds() // 60)
        return None

    @property
    def checklist_items(self):
        items = CHECKLISTS.get(self.kind, [])
        return [{"label": i, "done": bool((self.checklist or {}).get(i))} for i in items]


class LostItem(TimeStampedModel, PropertyScopedModel):
    """RF-HK-06: objetos perdidos y encontrados."""

    class Status(models.TextChoices):
        STORED = "stored", _("En custodia")
        RETURNED = "returned", _("Entregado al dueño")
        DONATED = "donated", _("Donado / descartado")

    found_at = models.DateField(_("fecha"))
    location = models.CharField(_("lugar"), max_length=100)
    room = models.ForeignKey("rooms.Room", null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(_("descripción"), max_length=255)
    photo = models.ImageField(_("foto"), upload_to="housekeeping/lost/", blank=True)
    found_by = models.CharField(_("encontrado por"), max_length=100, blank=True)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.STORED)
    owner_name = models.CharField(_("dueño"), max_length=150, blank=True)
    returned_at = models.DateField(_("entregado el"), null=True, blank=True)
    notes = models.CharField(_("notas"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("objeto perdido")
        verbose_name_plural = _("objetos perdidos")
        ordering = ["-found_at"]

    def __str__(self):
        return self.description


class LinenType(PropertyScopedModel):
    name = models.CharField(_("prenda"), max_length=100)
    par_level = models.PositiveIntegerField(_("stock ideal"), default=0)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("tipo de lencería")
        verbose_name_plural = _("tipos de lencería")
        ordering = ["name"]

    def __str__(self):
        return self.name


class LinenMovement(TimeStampedModel, PropertyScopedModel):
    """RF-HK-07: entrada y salida a lavandería, conteo por tipo y stock por piso."""

    class Direction(models.TextChoices):
        TO_LAUNDRY = "to_laundry", _("Enviado a lavandería")
        FROM_LAUNDRY = "from_laundry", _("Recibido de lavandería")
        PURCHASE = "purchase", _("Ingreso (compra)")
        DISCARD = "discard", _("Baja")

    linen = models.ForeignKey(
        LinenType, verbose_name=_("prenda"), on_delete=models.PROTECT, related_name="movements"
    )
    direction = models.CharField(_("movimiento"), max_length=15, choices=Direction.choices)
    quantity = models.PositiveIntegerField(_("cantidad"))
    floor = models.SmallIntegerField(_("piso"), null=True, blank=True)
    notes = models.CharField(_("notas"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("movimiento de lencería")
        verbose_name_plural = _("movimientos de lencería")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_direction_display()} {self.quantity} {self.linen}"


class MinibarItem(PropertyScopedModel):
    """RF-HK-05: artículos del minibar (descuentan del almacén desde la fase 2)."""

    name = models.CharField(_("artículo"), max_length=100)
    price = models.DecimalField(_("precio"), max_digits=10, decimal_places=2)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("artículo de minibar")
        verbose_name_plural = _("minibar")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.price})"
