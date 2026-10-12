"""Almacenes, artículos, kardex valorizado, lotes, inventario físico y mermas (RF-ALM-01 a RF-ALM-10)."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

QTY = {"max_digits": 14, "decimal_places": 3}
COST = {"max_digits": 14, "decimal_places": 4}
ZERO = Decimal("0")


class Warehouse(TimeStampedModel, PropertyScopedModel):
    """RF-ALM-01: múltiples almacenes con stock por ubicación."""

    class Kind(models.TextChoices):
        GENERAL = "general", _("General")
        KITCHEN = "kitchen", _("Cocina")
        BAR = "bar", _("Bar")
        HOUSEKEEPING = "housekeeping", _("Housekeeping")
        MAINTENANCE = "maintenance", _("Mantenimiento")

    code = models.SlugField(_("código"), max_length=20)
    name = models.CharField(_("nombre"), max_length=100)
    kind = models.CharField(_("tipo"), max_length=15, choices=Kind.choices, default=Kind.GENERAL)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("almacén")
        verbose_name_plural = _("almacenes")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_warehouse_code")]

    def __str__(self):
        return self.name


class ItemCategory(PropertyScopedModel):
    name = models.CharField(_("nombre"), max_length=100)

    class Meta:
        verbose_name = _("categoría de artículo")
        verbose_name_plural = _("categorías de artículos")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Item(TimeStampedModel, PropertyScopedModel):
    """RF-ALM-02: catálogo con unidad, equivalencias, mínimo y máximo."""

    class Unit(models.TextChoices):
        UNIT = "und", _("Unidad")
        KG = "kg", _("Kilogramo")
        G = "g", _("Gramo")
        L = "l", _("Litro")
        ML = "ml", _("Mililitro")
        PACK = "paq", _("Paquete")

    code = models.CharField(_("código"), max_length=30)
    name = models.CharField(_("nombre"), max_length=150)
    category = models.ForeignKey(ItemCategory, verbose_name=_("categoría"), null=True, blank=True,
                                 on_delete=models.SET_NULL)
    unit = models.CharField(_("unidad de consumo"), max_length=5, choices=Unit.choices, default=Unit.UNIT)
    purchase_unit = models.CharField(_("unidad de compra"), max_length=30, default="caja",
                                     help_text=_("Ej. caja, saco, botella"))
    purchase_factor = models.DecimalField(_("unidades por unidad de compra"), default=Decimal("1"), **QTY)
    min_stock = models.DecimalField(_("stock mínimo"), default=ZERO, **QTY)
    max_stock = models.DecimalField(_("stock máximo"), default=ZERO, **QTY)
    is_perishable = models.BooleanField(_("perecible (controla lotes y vencimiento)"), default=False)
    is_linen = models.BooleanField(_("lencería / menaje rotativo"), default=False)
    last_cost = models.DecimalField(_("último costo unitario"), default=ZERO, **COST)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("artículo")
        verbose_name_plural = _("artículos")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_item_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Stock(models.Model):
    """Saldo y costo promedio ponderado por almacén (RF-ALM-04)."""

    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stocks")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="stocks")
    quantity = models.DecimalField(_("cantidad"), default=ZERO, **QTY)
    avg_cost = models.DecimalField(_("costo promedio"), default=ZERO, **COST)

    class Meta:
        verbose_name = _("stock")
        constraints = [models.UniqueConstraint(fields=["warehouse", "item"], name="uniq_stock")]

    def __str__(self):
        return f"{self.item} @ {self.warehouse}: {self.quantity}"

    @property
    def value(self):
        return (self.quantity * self.avg_cost).quantize(Decimal("0.01"))


class Lot(models.Model):
    """RF-ALM-05: lotes y vencimientos."""

    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="lots")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="lots")
    code = models.CharField(_("lote"), max_length=40)
    expiry_date = models.DateField(_("vencimiento"), null=True, blank=True)
    quantity = models.DecimalField(_("cantidad"), default=ZERO, **QTY)

    class Meta:
        verbose_name = _("lote")
        verbose_name_plural = _("lotes")
        ordering = ["expiry_date"]

    def __str__(self):
        return f"{self.item.name} lote {self.code}"


class StockMovement(TimeStampedModel, PropertyScopedModel):
    """Kardex valorizado (RF-ALM-03, RF-ALM-04)."""

    class Kind(models.TextChoices):
        PURCHASE = "purchase", _("Ingreso por compra")
        REQUISITION = "requisition", _("Salida por requisición")
        TRANSFER_IN = "transfer_in", _("Transferencia (entrada)")
        TRANSFER_OUT = "transfer_out", _("Transferencia (salida)")
        ADJUST_IN = "adjust_in", _("Ajuste positivo")
        ADJUST_OUT = "adjust_out", _("Ajuste negativo")
        WASTE = "waste", _("Merma / baja")
        POS = "pos", _("Consumo restaurante (receta)")
        MINIBAR = "minibar", _("Consumo minibar")
        MAINTENANCE = "maintenance", _("Consumo mantenimiento")
        INITIAL = "initial", _("Saldo inicial")

    date = models.DateField(_("fecha"))
    warehouse = models.ForeignKey(Warehouse, verbose_name=_("almacén"), on_delete=models.PROTECT, related_name="movements")
    item = models.ForeignKey(Item, verbose_name=_("artículo"), on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(_("tipo"), max_length=15, choices=Kind.choices)
    quantity = models.DecimalField(_("cantidad (+ entra / − sale)"), **QTY)
    unit_cost = models.DecimalField(_("costo unitario"), **COST)
    total_cost = models.DecimalField(_("costo total"), max_digits=14, decimal_places=2)
    balance_qty = models.DecimalField(_("saldo"), **QTY)
    balance_avg_cost = models.DecimalField(_("costo promedio"), **COST)
    lot = models.ForeignKey(Lot, null=True, blank=True, on_delete=models.SET_NULL)
    reference = models.CharField(_("referencia"), max_length=60, blank=True)
    notes = models.CharField(_("notas"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("movimiento de almacén")
        verbose_name_plural = _("kardex")
        ordering = ["date", "created_at", "pk"]
        indexes = [models.Index(fields=["item", "warehouse", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.item.name}"


class StockCount(TimeStampedModel, PropertyScopedModel):
    """RF-ALM-06: inventario físico por conteo."""

    class Status(models.TextChoices):
        OPEN = "open", _("En conteo")
        CLOSED = "closed", _("Cerrado")

    warehouse = models.ForeignKey(Warehouse, verbose_name=_("almacén"), on_delete=models.PROTECT)
    date = models.DateField(_("fecha"))
    status = models.CharField(_("estado"), max_length=6, choices=Status.choices, default=Status.OPEN)
    notes = models.CharField(_("notas"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("inventario físico")
        verbose_name_plural = _("inventarios físicos")
        ordering = ["-date"]

    def __str__(self):
        return f"Inventario {self.warehouse} {self.date:%d/%m/%Y}"


class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    system_qty = models.DecimalField(_("sistema"), **QTY)
    counted_qty = models.DecimalField(_("contado"), null=True, blank=True, **QTY)

    class Meta:
        ordering = ["item__name"]

    @property
    def difference(self):
        return None if self.counted_qty is None else self.counted_qty - self.system_qty


class Waste(TimeStampedModel, PropertyScopedModel):
    """RF-ALM-08: mermas y bajas con aprobación y foto."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pendiente")
        APPROVED = "approved", _("Aprobada")
        REJECTED = "rejected", _("Rechazada")

    warehouse = models.ForeignKey(Warehouse, verbose_name=_("almacén"), on_delete=models.PROTECT)
    item = models.ForeignKey(Item, verbose_name=_("artículo"), on_delete=models.PROTECT)
    quantity = models.DecimalField(_("cantidad"), **QTY)
    reason = models.CharField(_("motivo"), max_length=255)
    photo = models.ImageField(_("foto"), upload_to="inventory/waste/", blank=True)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.PENDING)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        verbose_name = _("merma")
        verbose_name_plural = _("mermas y bajas")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.item.name} {self.quantity} ({self.get_status_display()})"


class RecipeLine(models.Model):
    """RF-POS-05: insumos por plato, descontados del almacén en cada venta."""

    menu_item = models.ForeignKey("pos.MenuItem", on_delete=models.CASCADE, related_name="recipe")
    item = models.ForeignKey(Item, verbose_name=_("insumo"), on_delete=models.PROTECT)
    quantity = models.DecimalField(_("cantidad por porción"), **QTY)

    class Meta:
        verbose_name = _("línea de receta")
        verbose_name_plural = _("recetas")

    def __str__(self):
        return f"{self.menu_item.name}: {self.quantity} {self.item.unit} {self.item.name}"
