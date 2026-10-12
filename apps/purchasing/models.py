"""Compras y proveedores (RF-COM-01 a RF-COM-05)."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}
QTY = {"max_digits": 14, "decimal_places": 3}
ZERO = Decimal("0")


class Supplier(TimeStampedModel, PropertyScopedModel):
    """RF-COM-04: proveedores con RUC validado, condiciones y evaluación."""

    ruc = models.CharField(_("RUC"), max_length=11)
    name = models.CharField(_("razón social"), max_length=200)
    contact_name = models.CharField(_("contacto"), max_length=150, blank=True)
    email = models.EmailField(_("correo"), blank=True)
    phone = models.CharField(_("teléfono"), max_length=30, blank=True)
    address = models.CharField(_("dirección"), max_length=255, blank=True)
    payment_days = models.PositiveSmallIntegerField(_("días de pago"), default=0)
    rating = models.PositiveSmallIntegerField(_("evaluación (1-5)"), default=3)
    notes = models.TextField(_("notas"), blank=True)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("proveedor")
        verbose_name_plural = _("proveedores")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Requisition(TimeStampedModel, PropertyScopedModel):
    """RF-COM-01: requisición interna por área con aprobación por monto."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Borrador")
        SUBMITTED = "submitted", _("Por aprobar")
        APPROVED = "approved", _("Aprobada")
        REJECTED = "rejected", _("Rechazada")
        ORDERED = "ordered", _("Con orden de compra")

    number = models.CharField(_("número"), max_length=20)
    warehouse = models.ForeignKey("inventory.Warehouse", verbose_name=_("área / almacén"), on_delete=models.PROTECT)
    needed_by = models.DateField(_("se necesita para"), null=True, blank=True)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(_("justificación"), blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("requisición")
        verbose_name_plural = _("requisiciones")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} · {self.warehouse}"

    @property
    def estimated_total(self) -> Decimal:
        return sum((ln.quantity * ln.estimated_cost for ln in self.lines.all()), ZERO).quantize(Decimal("0.01"))


class RequisitionLine(models.Model):
    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("inventory.Item", verbose_name=_("artículo"), on_delete=models.PROTECT)
    quantity = models.DecimalField(_("cantidad"), **QTY)
    estimated_cost = models.DecimalField(_("costo unitario estimado"), default=ZERO, **MONEY)

    def __str__(self):
        return f"{self.quantity} {self.item}"


class Quotation(TimeStampedModel):
    """RF-COM-02: cotizaciones comparativas."""

    requisition = models.ForeignKey(Requisition, on_delete=models.CASCADE, related_name="quotations")
    supplier = models.ForeignKey(Supplier, verbose_name=_("proveedor"), on_delete=models.PROTECT)
    delivery_days = models.PositiveSmallIntegerField(_("días de entrega"), default=1)
    notes = models.CharField(_("condiciones"), max_length=255, blank=True)
    selected = models.BooleanField(_("elegida"), default=False)

    class Meta:
        verbose_name = _("cotización")
        verbose_name_plural = _("cotizaciones")

    def __str__(self):
        return f"{self.supplier} · {self.total}"

    @property
    def total(self) -> Decimal:
        return sum((ln.quantity * ln.unit_price for ln in self.lines.all()), ZERO).quantize(Decimal("0.01"))


class QuotationLine(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT)
    quantity = models.DecimalField(**QTY)
    unit_price = models.DecimalField(**MONEY)


class PurchaseOrder(TimeStampedModel, PropertyScopedModel):
    """RF-COM-02/03: orden de compra con PDF y recepción parcial o total."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Borrador")
        SENT = "sent", _("Enviada")
        PARTIAL = "partial", _("Recibida parcialmente")
        RECEIVED = "received", _("Recibida")
        CANCELLED = "cancelled", _("Anulada")

    number = models.CharField(_("número"), max_length=20)
    supplier = models.ForeignKey(Supplier, verbose_name=_("proveedor"), on_delete=models.PROTECT, related_name="orders")
    requisition = models.ForeignKey(Requisition, null=True, blank=True, on_delete=models.SET_NULL)
    warehouse = models.ForeignKey("inventory.Warehouse", verbose_name=_("almacén de destino"), on_delete=models.PROTECT)
    order_date = models.DateField(_("fecha"))
    expected_date = models.DateField(_("entrega prevista"), null=True, blank=True)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(_("notas"), blank=True)

    class Meta:
        verbose_name = _("orden de compra")
        verbose_name_plural = _("órdenes de compra")
        ordering = ["-order_date", "-pk"]

    def __str__(self):
        return f"{self.number} · {self.supplier}"

    @property
    def total(self) -> Decimal:
        return sum((ln.quantity * ln.unit_price for ln in self.lines.all()), ZERO).quantize(Decimal("0.01"))


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("inventory.Item", verbose_name=_("artículo"), on_delete=models.PROTECT)
    quantity = models.DecimalField(_("cantidad"), **QTY)
    unit_price = models.DecimalField(_("precio unitario (sin IGV)"), **MONEY)
    received_qty = models.DecimalField(_("recibido"), default=ZERO, **QTY)

    @property
    def pending(self):
        return self.quantity - self.received_qty


class GoodsReceipt(TimeStampedModel, PropertyScopedModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    date = models.DateField(_("fecha"))
    guide_number = models.CharField(_("guía de remisión"), max_length=30, blank=True)
    invoice_number = models.CharField(_("factura del proveedor"), max_length=30, blank=True)

    class Meta:
        verbose_name = _("recepción de mercadería")
        verbose_name_plural = _("recepciones")
        ordering = ["-date"]

    def __str__(self):
        return f"Recepción {self.order.number} {self.date:%d/%m}"


class SupplierInvoice(TimeStampedModel, PropertyScopedModel):
    """RF-COM-05: cuentas por pagar con vencimientos."""

    supplier = models.ForeignKey(Supplier, verbose_name=_("proveedor"), on_delete=models.PROTECT,
                                 related_name="invoices")
    order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.SET_NULL)
    number = models.CharField(_("número de factura"), max_length=30)
    issue_date = models.DateField(_("emisión"))
    due_date = models.DateField(_("vencimiento"))
    amount = models.DecimalField(_("importe (con IGV)"), **MONEY)
    paid = models.BooleanField(_("pagada"), default=False)
    paid_at = models.DateField(_("fecha de pago"), null=True, blank=True)

    class Meta:
        verbose_name = _("factura de proveedor")
        verbose_name_plural = _("cuentas por pagar")
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.supplier} {self.number}"


def payables_total(property_obj):
    return SupplierInvoice.objects.filter(property=property_obj, paid=False).aggregate(s=Sum("amount"))["s"] or ZERO
