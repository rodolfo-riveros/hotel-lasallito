"""Folio del huésped, cargos, pagos y caja (RF-REC-09, RF-CAJ-01 a RF-CAJ-05).

Todo cargo pertenece a un folio y todo comprobante a uno o más cargos
(sección 8.3). Los montos se guardan en Decimal y en soles (PEN); los pagos en
dólares guardan además el monto original y el tipo de cambio.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}
ZERO = Decimal("0")


class Concept(TimeStampedModel, PropertyScopedModel):
    """Concepto de cargo: alojamiento, restaurante, lavandería, oxígeno, tours..."""

    class Category(models.TextChoices):
        LODGING = "lodging", _("Alojamiento")
        FNB = "fnb", _("Alimentos y bebidas")
        MINIBAR = "minibar", _("Minibar")
        LAUNDRY = "laundry", _("Lavandería")
        TOURS = "tours", _("Tours y traslados")
        SERVICES = "services", _("Otros servicios")
        PENALTY = "penalty", _("Penalidades")
        TIP = "tip", _("Propinas")

    code = models.SlugField(_("código"), max_length=30)
    name = models.CharField(_("nombre"), max_length=100)
    category = models.CharField(
        _("categoría"), max_length=10, choices=Category.choices, default=Category.SERVICES
    )
    default_price = models.DecimalField(_("precio sugerido"), default=ZERO, **MONEY)
    is_taxable = models.BooleanField(_("afecto a IGV"), default=True)
    is_invoiceable = models.BooleanField(_("se incluye en comprobante"), default=True)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("concepto de cargo")
        verbose_name_plural = _("conceptos de cargo")
        ordering = ["category", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_concept_code")]

    def __str__(self):
        return self.name

    @property
    def tax_category(self):
        return {"lodging": "lodging", "fnb": "fnb", "minibar": "fnb"}.get(self.category, "services")


class Folio(TimeStampedModel, PropertyScopedModel):
    class Kind(models.TextChoices):
        GUEST = "guest", _("Huésped")
        COMPANY = "company", _("Empresa")
        POS = "pos", _("Punto de venta")
        HOUSE = "house", _("Cuenta interna")

    class Status(models.TextChoices):
        OPEN = "open", _("Abierto")
        CLOSED = "closed", _("Cerrado")

    number = models.CharField(_("número"), max_length=20, db_index=True)
    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices, default=Kind.GUEST)
    status = models.CharField(_("estado"), max_length=6, choices=Status.choices, default=Status.OPEN)
    reservation = models.ForeignKey(
        "reservations.Reservation",
        verbose_name=_("reserva"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="folios",
    )
    is_main = models.BooleanField(_("folio principal"), default=False)
    guest = models.ForeignKey(
        "guests.Guest", null=True, blank=True, on_delete=models.PROTECT, related_name="folios"
    )
    company = models.ForeignKey(
        "guests.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="folios"
    )
    name = models.CharField(_("a nombre de"), max_length=200)
    closed_at = models.DateTimeField(_("cerrado el"), null=True, blank=True)

    class Meta:
        verbose_name = _("folio")
        verbose_name_plural = _("folios")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Folio {self.number} · {self.name}"

    @property
    def total_charges(self) -> Decimal:
        return self.charges.filter(is_void=False).aggregate(s=Sum("amount"))["s"] or ZERO

    @property
    def total_payments(self) -> Decimal:
        return self.payments.filter(is_void=False).aggregate(s=Sum("amount"))["s"] or ZERO

    @property
    def balance(self) -> Decimal:
        if "charges_total" in self.__dict__:  # anotado con folio.queries (sin N+1)
            return self.charges_total - self.payments_total
        return self.total_charges - self.total_payments

    @property
    def uninvoiced_charges(self):
        return self.charges.filter(is_void=False, invoice__isnull=True, concept__is_invoiceable=True)


class Charge(TimeStampedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", _("Manual")
        NIGHT_AUDIT = "night_audit", _("Cierre de día")
        POS = "pos", _("Punto de venta")
        MINIBAR = "minibar", _("Minibar")
        PENALTY = "penalty", _("Penalidad")
        EARLY_CHECKIN = "early_checkin", _("Early check-in")
        LATE_CHECKOUT = "late_checkout", _("Late check-out")
        TOUR = "tour", _("Tour / traslado")
        TRANSFER = "transfer", _("Transferido")
        PORTAL = "portal", _("Portal del huésped")

    folio = models.ForeignKey(
        Folio, verbose_name=_("folio"), on_delete=models.PROTECT, related_name="charges"
    )
    concept = models.ForeignKey(
        Concept, verbose_name=_("concepto"), on_delete=models.PROTECT, related_name="+"
    )
    service_date = models.DateField(_("fecha del servicio"))
    description = models.CharField(_("descripción"), max_length=200)
    quantity = models.DecimalField(_("cantidad"), max_digits=10, decimal_places=3, default=Decimal("1"))
    unit_price = models.DecimalField(_("precio unitario"), **MONEY)
    amount = models.DecimalField(_("importe (incluye impuestos)"), **MONEY)
    taxable_base = models.DecimalField(_("valor de venta"), default=ZERO, **MONEY)
    igv = models.DecimalField(_("IGV"), default=ZERO, **MONEY)
    service_charge = models.DecimalField(_("cargo por servicio"), default=ZERO, **MONEY)
    tax_exempt = models.BooleanField(_("exonerado / exportación"), default=False)
    source = models.CharField(_("origen"), max_length=15, choices=Source.choices, default=Source.MANUAL)
    reference = models.CharField(_("referencia"), max_length=60, blank=True)
    discount_percent = models.DecimalField(_("descuento (%)"), max_digits=5, decimal_places=2, default=ZERO)
    is_void = models.BooleanField(_("anulado"), default=False)
    void_reason = models.CharField(_("motivo de anulación"), max_length=200, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="charges"
    )

    class Meta:
        verbose_name = _("cargo")
        verbose_name_plural = _("cargos")
        ordering = ["service_date", "created_at"]
        indexes = [models.Index(fields=["service_date", "source"])]

    def __str__(self):
        return f"{self.description} {self.amount}"


class Payment(TimeStampedModel):
    """RF-CAJ-02: medios de pago."""

    class Method(models.TextChoices):
        CASH_PEN = "cash_pen", _("Efectivo S/")
        CASH_USD = "cash_usd", _("Efectivo US$")
        CARD = "card", _("Tarjeta (POS)")
        TRANSFER = "transfer", _("Transferencia")
        YAPE = "yape", _("Yape")
        PLIN = "plin", _("Plin")
        PAYMENT_LINK = "link", _("Enlace de pago / web")
        CITY_LEDGER = "ledger", _("Cuenta corriente (crédito)")

    CASH_METHODS = ("cash_pen", "cash_usd")

    folio = models.ForeignKey(
        Folio, verbose_name=_("folio"), on_delete=models.PROTECT, related_name="payments"
    )
    date = models.DateField(_("fecha"))
    method = models.CharField(_("medio de pago"), max_length=10, choices=Method.choices)
    currency = models.CharField(_("moneda"), max_length=3, default="PEN")
    amount_original = models.DecimalField(_("monto en la moneda del pago"), **MONEY)
    exchange_rate = models.DecimalField(
        _("tipo de cambio"), max_digits=10, decimal_places=4, default=Decimal("1")
    )
    amount = models.DecimalField(_("monto en soles"), **MONEY)
    reference = models.CharField(_("referencia / operación"), max_length=80, blank=True)
    is_deposit = models.BooleanField(_("adelanto / depósito"), default=False)
    is_refund = models.BooleanField(_("devolución"), default=False)
    tip = models.DecimalField(_("propina incluida"), default=ZERO, **MONEY)
    cash_session = models.ForeignKey(
        "folio.CashSession", null=True, blank=True, on_delete=models.PROTECT, related_name="payments"
    )
    is_void = models.BooleanField(_("anulado"), default=False)
    void_reason = models.CharField(_("motivo de anulación"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("pago")
        verbose_name_plural = _("pagos")
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.get_method_display()} {self.amount}"


class CashRegister(TimeStampedModel, PropertyScopedModel):
    name = models.CharField(_("nombre"), max_length=100)
    outlet = models.ForeignKey(
        "pos.Outlet", verbose_name=_("punto de venta"), null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("caja")
        verbose_name_plural = _("cajas")

    def __str__(self):
        return self.name


class CashSession(TimeStampedModel, PropertyScopedModel):
    """RF-CAJ-01: apertura y cierre por turno y usuario, con arqueo."""

    class Status(models.TextChoices):
        OPEN = "open", _("Abierta")
        CLOSED = "closed", _("Cerrada")

    register = models.ForeignKey(
        CashRegister, verbose_name=_("caja"), on_delete=models.PROTECT, related_name="sessions"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("cajero"), on_delete=models.PROTECT)
    business_date = models.DateField(_("fecha hotelera"))
    opened_at = models.DateTimeField(_("apertura"), auto_now_add=True)
    opening_pen = models.DecimalField(_("fondo inicial S/"), default=ZERO, **MONEY)
    opening_usd = models.DecimalField(_("fondo inicial US$"), default=ZERO, **MONEY)
    closed_at = models.DateTimeField(_("cierre"), null=True, blank=True)
    status = models.CharField(_("estado"), max_length=6, choices=Status.choices, default=Status.OPEN)
    expected = models.JSONField(_("esperado por medio"), default=dict, blank=True)
    counted = models.JSONField(_("contado por medio"), default=dict, blank=True)
    difference = models.DecimalField(_("diferencia S/"), default=ZERO, **MONEY)
    notes = models.TextField(_("observaciones"), blank=True)

    class Meta:
        verbose_name = _("turno de caja")
        verbose_name_plural = _("turnos de caja")
        ordering = ["-opened_at"]

    def __str__(self):
        return f"{self.register} · {self.user} · {self.business_date:%d/%m/%Y}"


class PettyCashExpense(TimeStampedModel):
    """RF-CAJ-04: caja chica con rendición de gastos."""

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="expenses")
    description = models.CharField(_("descripción"), max_length=200)
    amount = models.DecimalField(_("monto S/"), **MONEY)
    receipt = models.CharField(_("comprobante"), max_length=60, blank=True)

    class Meta:
        verbose_name = _("gasto de caja chica")
        verbose_name_plural = _("gastos de caja chica")

    def __str__(self):
        return f"{self.description} {self.amount}"
