"""Restaurante, bar y servicios (RF-POS-01 a RF-POS-08)."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

MONEY = {"max_digits": 10, "decimal_places": 2}


class Outlet(TimeStampedModel, PropertyScopedModel):
    """RF-POS-01: puntos de venta configurables."""

    class Kind(models.TextChoices):
        RESTAURANT = "restaurant", _("Restaurante")
        BAR = "bar", _("Bar")
        ROOM_SERVICE = "room_service", _("Room service")
        SHOP = "shop", _("Tienda")
        SPA = "spa", _("Spa")
        TOURS = "tours", _("Tours")

    name = models.CharField(_("nombre"), max_length=100)
    kind = models.CharField(_("tipo"), max_length=15, choices=Kind.choices, default=Kind.RESTAURANT)
    concept = models.ForeignKey(
        "folio.Concept", verbose_name=_("concepto de cargo"), null=True, blank=True, on_delete=models.SET_NULL
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        verbose_name=_("almacén que descuenta las recetas"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("punto de venta")
        verbose_name_plural = _("puntos de venta")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Table(models.Model):
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name="tables")
    number = models.CharField(_("mesa"), max_length=10)
    seats = models.PositiveSmallIntegerField(_("asientos"), default=4)
    pos_x = models.PositiveSmallIntegerField(_("posición X (%)"), default=10)
    pos_y = models.PositiveSmallIntegerField(_("posición Y (%)"), default=10)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("mesa")
        verbose_name_plural = _("mesas")
        ordering = ["outlet", "number"]
        constraints = [models.UniqueConstraint(fields=["outlet", "number"], name="uniq_table_number")]

    def __str__(self):
        return f"{self.outlet} · Mesa {self.number}"


class MenuCategory(PropertyScopedModel):
    name = models.CharField(_("nombre"), max_length=100)
    name_en = models.CharField(_("nombre (inglés)"), max_length=100, blank=True)
    name_pt = models.CharField(_("nombre (portugués)"), max_length=100, blank=True)
    sort_order = models.PositiveSmallIntegerField(_("orden"), default=0)

    class Meta:
        verbose_name = _("categoría de carta")
        verbose_name_plural = _("categorías de carta")
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class MenuItem(TimeStampedModel, PropertyScopedModel):
    """RF-POS-03: carta digital en tres idiomas con alérgenos y fotos."""

    class Station(models.TextChoices):
        KITCHEN = "kitchen", _("Cocina")
        BAR = "bar", _("Barra")
        NONE = "none", _("Sin preparación")

    outlets = models.ManyToManyField(Outlet, verbose_name=_("puntos de venta"), related_name="menu_items")
    category = models.ForeignKey(
        MenuCategory, verbose_name=_("categoría"), on_delete=models.PROTECT, related_name="items"
    )
    name = models.CharField(_("nombre"), max_length=120)
    name_en = models.CharField(_("nombre (inglés)"), max_length=120, blank=True)
    name_pt = models.CharField(_("nombre (portugués)"), max_length=120, blank=True)
    description = models.CharField(_("descripción"), max_length=255, blank=True)
    description_en = models.CharField(_("descripción (inglés)"), max_length=255, blank=True)
    description_pt = models.CharField(_("descripción (portugués)"), max_length=255, blank=True)
    price = models.DecimalField(_("precio (incluye IGV)"), **MONEY)
    allergens = models.CharField(
        _("alérgenos"), max_length=200, blank=True, help_text=_("Ej. gluten, lácteos, maní")
    )
    photo = models.ImageField(_("foto"), upload_to="pos/menu/", blank=True)
    station = models.CharField(
        _("se prepara en"), max_length=10, choices=Station.choices, default=Station.KITCHEN
    )
    is_available = models.BooleanField(_("disponible"), default=True)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("plato o bebida")
        verbose_name_plural = _("carta")
        ordering = ["category__sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.price})"


class Order(TimeStampedModel, PropertyScopedModel):
    """RF-POS-02: comanda / cuenta de una mesa o de room service."""

    class Status(models.TextChoices):
        OPEN = "open", _("Abierta")
        CLOSED = "closed", _("Cerrada")
        CANCELLED = "cancelled", _("Anulada")

    class Settlement(models.TextChoices):
        ROOM = "room", _("Cargo a habitación")
        PAID = "paid", _("Pagada")

    number = models.CharField(_("número"), max_length=20)
    outlet = models.ForeignKey(
        Outlet, verbose_name=_("punto de venta"), on_delete=models.PROTECT, related_name="orders"
    )
    table = models.ForeignKey(Table, verbose_name=_("mesa"), null=True, blank=True, on_delete=models.SET_NULL)
    waiter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("mozo"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    covers = models.PositiveSmallIntegerField(_("comensales"), default=1)
    reservation = models.ForeignKey(
        "reservations.Reservation",
        verbose_name=_("habitación (huésped)"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_orders",
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="splits"
    )
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.OPEN)
    settlement = models.CharField(_("liquidación"), max_length=5, choices=Settlement.choices, blank=True)
    tip = models.DecimalField(_("propina"), default=Decimal("0"), **MONEY)
    folio = models.ForeignKey(
        "folio.Folio", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    signature = models.TextField(_("firma del huésped"), blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(_("notas"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("comanda")
        verbose_name_plural = _("comandas")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} · {self.table or self.outlet}"

    @property
    def total(self) -> Decimal:
        return sum((i.total for i in self.items.exclude(status=OrderItem.Status.VOID)), Decimal("0"))


class OrderItem(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Por enviar")
        SENT = "sent", _("En cocina")
        PREPARING = "preparing", _("Preparando")
        READY = "ready", _("Listo")
        SERVED = "served", _("Servido")
        VOID = "void", _("Anulado")

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, verbose_name=_("plato"), on_delete=models.PROTECT)
    quantity = models.PositiveSmallIntegerField(_("cantidad"), default=1)
    unit_price = models.DecimalField(_("precio"), **MONEY)
    notes = models.CharField(_("indicaciones"), max_length=150, blank=True)
    station = models.CharField(max_length=10, default="kitchen")
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.quantity} × {self.menu_item.name}"

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


class BreakfastLog(TimeStampedModel, PropertyScopedModel):
    """RF-POS-06: control de desayunos incluidos y desayunos para llevar (Machu Picchu)."""

    class Kind(models.TextChoices):
        RESTAURANT = "restaurant", _("En restaurante")
        BOX = "box", _("Para llevar (box lunch)")
        EARLY = "early", _("Temprano")

    reservation = models.ForeignKey(
        "reservations.Reservation", on_delete=models.CASCADE, related_name="breakfasts"
    )
    date = models.DateField(_("fecha"))
    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices, default=Kind.RESTAURANT)
    pax = models.PositiveSmallIntegerField(_("personas"), default=1)
    served = models.BooleanField(_("servido"), default=False)
    served_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(_("notas"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("desayuno")
        verbose_name_plural = _("control de desayunos")
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["reservation", "date", "kind"], name="uniq_breakfast_per_day"),
        ]

    def __str__(self):
        return f"{self.reservation.code} {self.date:%d/%m} {self.get_kind_display()}"
