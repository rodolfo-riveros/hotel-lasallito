"""Comprobantes electrónicos (RF-FAC-01 a RF-FAC-10) contra el simulador SUNAT (sección 12)."""

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, SoftDeleteModel, TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}
ZERO = Decimal("0")


class DocType(models.TextChoices):
    FACTURA = "01", _("Factura")
    BOLETA = "03", _("Boleta de venta")
    CREDIT_NOTE = "07", _("Nota de crédito")
    DEBIT_NOTE = "08", _("Nota de débito")
    REMISSION = "09", _("Guía de remisión")


class CustomerDocType(models.TextChoices):
    NONE = "0", _("Sin documento")
    DNI = "1", _("DNI")
    CE = "4", _("Carné de extranjería")
    RUC = "6", _("RUC")
    PASSPORT = "7", _("Pasaporte")


class Series(TimeStampedModel, PropertyScopedModel):
    """RF-FAC-01: series por sede y punto de venta, con correlativo."""

    doc_type = models.CharField(_("tipo"), max_length=2, choices=DocType.choices)
    code = models.CharField(_("serie"), max_length=4, help_text=_("Ej. F001, B001, FC01, BC01"))
    next_number = models.PositiveIntegerField(_("siguiente número"), default=1)
    outlet = models.ForeignKey(
        "pos.Outlet", verbose_name=_("punto de venta"), null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("serie")
        verbose_name_plural = _("series")
        ordering = ["doc_type", "code"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_series_code")]

    def __str__(self):
        return f"{self.code} ({self.get_doc_type_display()})"


class Invoice(TimeStampedModel, SoftDeleteModel, PropertyScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pendiente de envío")
        ACCEPTED = "accepted", _("Aceptado")
        OBSERVED = "observed", _("Aceptado con observaciones")
        REJECTED = "rejected", _("Rechazado")
        VOIDED = "voided", _("Dado de baja")

    series = models.ForeignKey(
        Series, verbose_name=_("serie"), on_delete=models.PROTECT, related_name="invoices"
    )
    number = models.PositiveIntegerField(_("número"))
    doc_type = models.CharField(_("tipo"), max_length=2, choices=DocType.choices)
    issue_date = models.DateField(_("fecha de emisión"))
    due_date = models.DateField(_("vencimiento"), null=True, blank=True)
    currency = models.CharField(_("moneda"), max_length=3, default="PEN")
    exchange_rate = models.DecimalField(
        _("tipo de cambio"), max_digits=10, decimal_places=4, default=Decimal("1")
    )
    customer_doc_type = models.CharField(
        _("tipo de documento"), max_length=1, choices=CustomerDocType.choices
    )
    customer_doc = models.CharField(_("número de documento"), max_length=20, blank=True)
    customer_name = models.CharField(_("cliente"), max_length=200)
    customer_address = models.CharField(_("dirección"), max_length=255, blank=True)
    customer_email = models.EmailField(_("correo"), blank=True)
    company = models.ForeignKey("guests.Company", null=True, blank=True, on_delete=models.SET_NULL)
    folio = models.ForeignKey(
        "folio.Folio", null=True, blank=True, on_delete=models.PROTECT, related_name="invoices"
    )
    related_invoice = models.ForeignKey(
        "self",
        verbose_name=_("comprobante que modifica"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notes",
    )
    note_reason_code = models.CharField(_("motivo (catálogo 09/10)"), max_length=2, blank=True)
    note_reason = models.CharField(_("sustento"), max_length=255, blank=True)
    is_advance = models.BooleanField(_("anticipo"), default=False)
    taxed_amount = models.DecimalField(_("op. gravadas"), default=ZERO, **MONEY)
    exempt_amount = models.DecimalField(_("op. exoneradas"), default=ZERO, **MONEY)
    export_amount = models.DecimalField(_("exportación de servicios"), default=ZERO, **MONEY)
    igv = models.DecimalField(_("IGV"), default=ZERO, **MONEY)
    other_charges = models.DecimalField(_("otros cargos (servicio)"), default=ZERO, **MONEY)
    total = models.DecimalField(_("importe total"), default=ZERO, **MONEY)
    legends = models.JSONField(_("leyendas"), default=list, blank=True)
    status = models.CharField(
        _("estado SUNAT"), max_length=10, choices=Status.choices, default=Status.PENDING
    )
    sunat_code = models.CharField(_("código de respuesta"), max_length=10, blank=True)
    sunat_message = models.CharField(_("mensaje de respuesta"), max_length=255, blank=True)
    hash = models.CharField(_("código hash"), max_length=64, blank=True)
    send_attempts = models.PositiveSmallIntegerField(_("intentos de envío"), default=0)
    is_simulated = models.BooleanField(_("simulación"), default=True)
    is_paid = models.BooleanField(_("pagado"), default=True)
    paid_at = models.DateField(_("fecha de pago"), null=True, blank=True)
    voided_at = models.DateTimeField(_("baja el"), null=True, blank=True)
    void_reason = models.CharField(_("motivo de baja"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("comprobante")
        verbose_name_plural = _("comprobantes")
        ordering = ["-issue_date", "-number"]
        constraints = [models.UniqueConstraint(fields=["series", "number"], name="uniq_invoice_number")]

    def __str__(self):
        return self.full_number

    @property
    def full_number(self):
        return f"{self.series.code}-{self.number:08d}"

    @property
    def is_credit_note(self):
        return self.doc_type == DocType.CREDIT_NOTE

    @property
    def sign(self):
        return -1 if self.is_credit_note else 1


class InvoiceLine(models.Model):
    class Affectation(models.TextChoices):
        TAXED = "10", _("Gravado")
        EXEMPT = "20", _("Exonerado")
        UNAFFECTED = "30", _("Inafecto")
        EXPORT = "40", _("Exportación")

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    charge = models.ForeignKey(
        "folio.Charge", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    description = models.CharField(_("descripción"), max_length=255)
    unit_code = models.CharField(_("unidad"), max_length=5, default="ZZ")
    quantity = models.DecimalField(_("cantidad"), max_digits=10, decimal_places=3, default=Decimal("1"))
    unit_price = models.DecimalField(_("precio unitario"), **MONEY)
    affectation = models.CharField(_("afectación IGV"), max_length=2, choices=Affectation.choices)
    base = models.DecimalField(_("valor de venta"), **MONEY)
    igv = models.DecimalField(_("IGV"), default=ZERO, **MONEY)
    other = models.DecimalField(_("otros cargos"), default=ZERO, **MONEY)
    total = models.DecimalField(_("total"), **MONEY)

    class Meta:
        verbose_name = _("línea")
        verbose_name_plural = _("líneas")

    def __str__(self):
        return self.description


class SunatSubmission(models.Model):
    """RNF-DIS-04: registro de cada envío y respuesta (incluye fallas)."""

    class Kind(models.TextChoices):
        SEND = "send", _("Envío")
        VOID = "void", _("Comunicación de baja")
        SUMMARY = "summary", _("Resumen diario")

    property = models.ForeignKey("core.Property", on_delete=models.CASCADE, related_name="+")
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.CASCADE, related_name="submissions"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SEND)
    created_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    connection_error = models.BooleanField(default=False)
    code = models.CharField(max_length=10, blank=True)
    message = models.CharField(max_length=255, blank=True)
    ticket = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.created_at:%d/%m %H:%M} {self.code}"


class SimulationSettings(models.Model):
    """Controles del docente para practicar fallas de SUNAT (sección 12, RF-SIM-04)."""

    property = models.OneToOneField(
        "core.Property", on_delete=models.CASCADE, related_name="sunat_simulation"
    )
    connection_down = models.BooleanField(_("simular caída de conexión con SUNAT"), default=False)
    reject_next = models.PositiveSmallIntegerField(_("rechazar los próximos N comprobantes"), default=0)
    reject_message = models.CharField(
        _("mensaje de rechazo"),
        max_length=200,
        default="2800 - El dato ingresado en el tipo de documento no es válido",
    )

    class Meta:
        verbose_name = _("simulación SUNAT")

    def __str__(self):
        return f"Simulación SUNAT {self.property}"


class FakeTaxpayer(models.Model):
    """Padrón local de contribuyentes ficticios para la consulta RUC (sección 12)."""

    ruc = models.CharField(_("RUC"), max_length=11, unique=True)
    legal_name = models.CharField(_("razón social"), max_length=200)
    address = models.CharField(_("dirección fiscal"), max_length=255, blank=True)
    status = models.CharField(_("estado"), max_length=20, default="ACTIVO")
    condition = models.CharField(_("condición"), max_length=20, default="HABIDO")

    class Meta:
        verbose_name = _("contribuyente ficticio")
        verbose_name_plural = _("contribuyentes ficticios")

    def __str__(self):
        return f"{self.ruc} {self.legal_name}"


class FakePerson(models.Model):
    """Padrón local de personas ficticias para la consulta DNI (sección 12)."""

    dni = models.CharField(_("DNI"), max_length=8, unique=True)
    first_name = models.CharField(_("nombres"), max_length=100)
    last_name = models.CharField(_("apellidos"), max_length=100)

    class Meta:
        verbose_name = _("persona ficticia")
        verbose_name_plural = _("personas ficticias")

    def __str__(self):
        return f"{self.dni} {self.first_name} {self.last_name}"
