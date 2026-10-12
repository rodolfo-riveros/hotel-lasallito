"""Habitaciones y tipos (RF-HAB-01 a RF-HAB-05)."""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class RoomType(TimeStampedModel, PropertyScopedModel):
    """RF-HAB-01: catálogo de tipos con textos en tres idiomas."""

    code = models.SlugField(_("código"), max_length=20)
    name = models.CharField(_("nombre"), max_length=100)
    name_en = models.CharField(_("nombre (inglés)"), max_length=100, blank=True)
    name_pt = models.CharField(_("nombre (portugués)"), max_length=100, blank=True)
    description = models.TextField(_("descripción"), blank=True)
    description_en = models.TextField(_("descripción (inglés)"), blank=True)
    description_pt = models.TextField(_("descripción (portugués)"), blank=True)
    base_occupancy = models.PositiveSmallIntegerField(
        _("ocupación incluida en la tarifa"), default=2, help_text=_("Adultos incluidos en el precio base.")
    )
    max_adults = models.PositiveSmallIntegerField(_("máximo de adultos"), default=2)
    max_children = models.PositiveSmallIntegerField(_("máximo de niños"), default=1)
    max_occupancy = models.PositiveSmallIntegerField(_("ocupación máxima"), default=3)
    beds = models.CharField(_("camas"), max_length=100, blank=True, help_text=_("Ej. 1 queen, 2 twin"))
    size_m2 = models.PositiveSmallIntegerField(_("tamaño (m²)"), null=True, blank=True)
    amenities = models.TextField(
        _("comodidades"), blank=True, help_text=_("Una por línea: wifi, calefacción, caja fuerte...")
    )
    photo = models.ImageField(_("foto"), upload_to="rooms/types/", blank=True)
    sort_order = models.PositiveSmallIntegerField(_("orden"), default=0)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("tipo de habitación")
        verbose_name_plural = _("tipos de habitación")
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_roomtype_code")]

    def __str__(self):
        return self.name

    @property
    def amenity_list(self):
        return [a.strip() for a in self.amenities.splitlines() if a.strip()]


class Room(TimeStampedModel, PropertyScopedModel):
    """RF-HAB-02: habitación física con su estado de limpieza (RF-HK-01)."""

    class View(models.TextChoices):
        MOUNTAIN = "mountain", _("Montaña")
        GARDEN = "garden", _("Jardín")
        STREET = "street", _("Calle")
        COURTYARD = "courtyard", _("Patio")
        RIVER = "river", _("Río")
        INTERIOR = "interior", _("Interior")

    class HKStatus(models.TextChoices):
        CLEAN = "clean", _("Limpia")
        DIRTY = "dirty", _("Sucia")
        CLEANING = "cleaning", _("En limpieza")
        INSPECTED = "inspected", _("Inspeccionada")

    number = models.CharField(_("número"), max_length=10)
    room_type = models.ForeignKey(
        RoomType, verbose_name=_("tipo"), on_delete=models.PROTECT, related_name="rooms"
    )
    floor = models.SmallIntegerField(_("piso"), default=1)
    view = models.CharField(_("vista"), max_length=20, choices=View.choices, default=View.GARDEN)
    location = models.CharField(_("ubicación"), max_length=100, blank=True, help_text=_("Ej. ala norte"))
    has_heating = models.BooleanField(_("calefacción"), default=True)
    has_oxygen = models.BooleanField(_("oxígeno"), default=False)
    has_balcony = models.BooleanField(_("balcón"), default=False)
    is_accessible = models.BooleanField(_("accesible"), default=False)
    is_quiet = models.BooleanField(_("zona silenciosa"), default=False)
    connecting_rooms = models.ManyToManyField(
        "self", verbose_name=_("habitaciones conectadas"), blank=True, symmetrical=True
    )
    hk_status = models.CharField(
        _("estado de limpieza"), max_length=10, choices=HKStatus.choices, default=HKStatus.CLEAN
    )
    notes = models.TextField(_("notas"), blank=True)
    sort_order = models.PositiveSmallIntegerField(_("orden"), default=0)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("habitación")
        verbose_name_plural = _("habitaciones")
        ordering = ["floor", "sort_order", "number"]
        constraints = [models.UniqueConstraint(fields=["property", "number"], name="uniq_room_number")]

    def __str__(self):
        return f"{self.number} · {self.room_type}"

    @property
    def is_ready(self):
        return self.hk_status in (self.HKStatus.CLEAN, self.HKStatus.INSPECTED)

    def active_block(self, date=None):
        date = date or timezone.localdate()
        return self.blocks.filter(is_active=True, start_date__lte=date, end_date__gt=date).first()


class RoomBlock(TimeStampedModel, PropertyScopedModel):
    """RF-HAB-03: bloqueo por mantenimiento, remodelación o uso interno."""

    class Kind(models.TextChoices):
        MAINTENANCE = "maintenance", _("Mantenimiento")
        REMODEL = "remodel", _("Remodelación")
        INTERNAL = "internal", _("Uso interno")
        OUT_OF_ORDER = "out_of_order", _("Fuera de servicio")

    room = models.ForeignKey(
        Room, verbose_name=_("habitación"), on_delete=models.CASCADE, related_name="blocks"
    )
    kind = models.CharField(_("tipo"), max_length=20, choices=Kind.choices, default=Kind.MAINTENANCE)
    start_date = models.DateField(_("desde"))
    end_date = models.DateField(_("hasta (exclusive)"))
    reason = models.CharField(_("motivo"), max_length=255)
    is_active = models.BooleanField(_("vigente"), default=True)

    class Meta:
        verbose_name = _("bloqueo de habitación")
        verbose_name_plural = _("bloqueos de habitación")
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")), name="block_dates_valid"
            )
        ]

    def __str__(self):
        return f"{self.room.number}: {self.get_kind_display()} {self.start_date:%d/%m}–{self.end_date:%d/%m}"


class RoomInventoryItem(models.Model):
    """RF-HAB-05: inventario de cada habitación para revisión de housekeeping."""

    room = models.ForeignKey(
        Room, verbose_name=_("habitación"), on_delete=models.CASCADE, related_name="inventory"
    )
    name = models.CharField(_("artículo"), max_length=100)
    quantity = models.PositiveSmallIntegerField(_("cantidad"), default=1)
    notes = models.CharField(_("notas"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("artículo de habitación")
        verbose_name_plural = _("inventario de habitación")
        ordering = ["name"]

    def __str__(self):
        return f"{self.quantity} × {self.name}"
