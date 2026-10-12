"""Modelos del núcleo: propiedad, monedas, tipo de cambio, impuestos y auditoría.

Reglas de la sección 8.3 que se apoyan aquí:
- Montos y tasas en Decimal, nunca en float.
- Borrado lógico y registro de creador / fecha / última modificación.
- Cada registro operativo lleva su `property`.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .request_context import get_current_user

# --------------------------------------------------------------------------
# Modelos abstractos reutilizables
# --------------------------------------------------------------------------


class TimeStampedModel(models.Model):
    """Registra quién creó y modificó por última vez el registro, y cuándo."""

    created_at = models.DateTimeField(_("creado el"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modificado el"), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("creado por"),
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("modificado por"),
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        user = get_current_user()
        if user is not None:
            if self._state.adding and self.created_by_id is None:
                self.created_by = user
            self.updated_by = user
        super().save(*args, **kwargs)


class AliveManager(models.Manager):
    """Devuelve solo los registros no eliminados."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteModel(models.Model):
    """Borrado lógico (RNF-INT-03): `delete()` marca, nunca borra la fila."""

    is_deleted = models.BooleanField(_("eliminado"), default=False, db_index=True)
    deleted_at = models.DateTimeField(_("eliminado el"), null=True, blank=True, editable=False)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("eliminado por"),
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = AliveManager()
    all_objects = models.Manager()  # noqa: DJ012 (es un manager, no un campo)

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = get_current_user()
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
        return (0, {})

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def hard_delete(self):
        raise ValidationError(_("El borrado físico no está permitido en este registro."))


class PropertyScopedModel(models.Model):
    """Todo registro operativo pertenece a una propiedad (hotel)."""

    property = models.ForeignKey(
        "core.Property",
        verbose_name=_("propiedad"),
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True


# --------------------------------------------------------------------------
# Propiedad (hotel)
# --------------------------------------------------------------------------

ruc_validator = RegexValidator(r"^(10|15|17|20)\d{9}$", _("El RUC debe tener 11 dígitos válidos."))
hex_color_validator = RegexValidator(r"^#[0-9A-Fa-f]{6}$", _("Use un color hexadecimal, ej. #7A1E2C."))


class Property(TimeStampedModel, SoftDeleteModel):
    class Kind(models.TextChoices):
        HOTEL = "hotel", _("Hotel")
        HOSTAL = "hostal", _("Hostal")
        BOUTIQUE = "boutique", _("Hotel boutique")

    code = models.SlugField(_("código"), max_length=30, unique=True)
    name = models.CharField(_("nombre comercial"), max_length=150)
    legal_name = models.CharField(_("razón social"), max_length=200)
    ruc = models.CharField(_("RUC"), max_length=11, validators=[ruc_validator])
    kind = models.CharField(_("tipo"), max_length=20, choices=Kind.choices, default=Kind.HOTEL)
    category_stars = models.PositiveSmallIntegerField(
        _("estrellas"), default=3, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    address = models.CharField(_("dirección"), max_length=255, blank=True)
    district = models.CharField(_("distrito"), max_length=100, default="Cusco")
    city = models.CharField(_("ciudad"), max_length=100, default="Cusco")
    ubigeo = models.CharField(_("ubigeo"), max_length=6, default="080101")
    phone = models.CharField(_("teléfono"), max_length=30, blank=True)
    email = models.EmailField(_("correo"), blank=True)
    website = models.URLField(_("sitio web"), blank=True)
    time_zone = models.CharField(_("zona horaria"), max_length=50, default="America/Lima")
    base_currency = models.ForeignKey(
        "core.Currency",
        verbose_name=_("moneda base"),
        on_delete=models.PROTECT,
        related_name="+",
        default="PEN",
    )
    check_in_time = models.TimeField(_("hora de check-in"), default="14:00")
    check_out_time = models.TimeField(_("hora de check-out"), default="11:00")
    # RNF-UX-01: identidad configurable por propiedad
    logo = models.ImageField(_("logo"), upload_to="properties/logos/", blank=True)
    brand_color = models.CharField(
        _("color de marca"), max_length=7, default="#7A1E2C", validators=[hex_color_validator]
    )
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("propiedad")
        verbose_name_plural = _("propiedades")
        ordering = ["name"]

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------
# Monedas y tipo de cambio (RF-TAR-03, RF-FAC-07)
# --------------------------------------------------------------------------


class Currency(models.Model):
    code = models.CharField(_("código ISO"), max_length=3, primary_key=True)
    name = models.CharField(_("nombre"), max_length=50)
    symbol = models.CharField(_("símbolo"), max_length=5)
    decimals = models.PositiveSmallIntegerField(_("decimales"), default=2)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("moneda")
        verbose_name_plural = _("monedas")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.symbol})"


class ExchangeRate(TimeStampedModel):
    """Tipo de cambio diario respecto a la moneda base (PEN).

    En esta versión lo edita a mano el administrador o el docente (sección 12).
    """

    class Source(models.TextChoices):
        MANUAL = "manual", _("Manual")
        SUNAT = "sunat", _("SUNAT")

    date = models.DateField(_("fecha"))
    currency = models.ForeignKey(
        Currency, verbose_name=_("moneda"), on_delete=models.PROTECT, related_name="rates"
    )
    buy = models.DecimalField(
        _("compra"), max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    sell = models.DecimalField(
        _("venta"), max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    source = models.CharField(_("fuente"), max_length=10, choices=Source.choices, default=Source.MANUAL)

    class Meta:
        verbose_name = _("tipo de cambio")
        verbose_name_plural = _("tipos de cambio")
        ordering = ["-date", "currency"]
        constraints = [
            models.UniqueConstraint(fields=["date", "currency"], name="uniq_exchange_rate_per_day"),
            models.CheckConstraint(
                condition=models.Q(sell__gte=models.F("buy")), name="exchange_sell_gte_buy"
            ),
        ]

    def __str__(self):
        return f"{self.currency_id} {self.date:%d/%m/%Y}: C {self.buy} / V {self.sell}"

    @classmethod
    def for_date(cls, currency_code, date=None):
        """Último tipo de cambio vigente a la fecha indicada (o None)."""
        date = date or timezone.localdate()
        return cls.objects.filter(currency_id=currency_code, date__lte=date).order_by("-date").first()


# --------------------------------------------------------------------------
# Impuestos (RF-TAR-06)
# --------------------------------------------------------------------------


class TaxRule(TimeStampedModel, PropertyScopedModel):
    class AppliesTo(models.TextChoices):
        ALL = "all", _("Todo")
        LODGING = "lodging", _("Alojamiento")
        FOOD_BEVERAGE = "fnb", _("Alimentos y bebidas")
        SERVICES = "services", _("Otros servicios")

    code = models.SlugField(_("código"), max_length=30)
    name = models.CharField(_("nombre"), max_length=100)
    rate = models.DecimalField(
        _("tasa (%)"),
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    applies_to = models.CharField(
        _("aplica a"), max_length=10, choices=AppliesTo.choices, default=AppliesTo.ALL
    )
    is_included_in_price = models.BooleanField(_("incluido en el precio"), default=True)
    exempt_for_non_domiciled = models.BooleanField(
        _("exonerado a no domiciliados"),
        default=False,
        help_text=_("IGV 0% por alojamiento a extranjeros no domiciliados con pasaporte registrado."),
    )
    order = models.PositiveSmallIntegerField(_("orden"), default=0)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("impuesto")
        verbose_name_plural = _("impuestos")
        ordering = ["property", "order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["property", "code"], name="uniq_tax_code_per_property"),
        ]

    def __str__(self):
        return f"{self.name} {self.rate}%"


# --------------------------------------------------------------------------
# Auditoría inmutable (RNF-SEG-03)
# --------------------------------------------------------------------------


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(_("La auditoría no se puede modificar."))

    def delete(self):
        raise ValidationError(_("La auditoría no se puede eliminar."))


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", _("Creación")
        UPDATE = "update", _("Modificación")
        DELETE = "delete", _("Eliminación")
        RESTORE = "restore", _("Restauración")
        VOID = "void", _("Anulación")
        APPROVE = "approve", _("Aprobación")
        DISCOUNT = "discount", _("Descuento")
        RATE_CHANGE = "rate_change", _("Cambio de tarifa")
        CASH_CLOSE = "cash_close", _("Cierre de caja")
        LOGIN = "login", _("Inicio de sesión")
        LOGIN_FAILED = "login_failed", _("Inicio de sesión fallido")
        LOGOUT = "logout", _("Cierre de sesión")
        VIEW_SENSITIVE = "view_sensitive", _("Acceso a datos personales")
        PERMISSION = "permission", _("Cambio de permisos")
        EXPORT = "export", _("Exportación")

    timestamp = models.DateTimeField(_("fecha y hora"), default=timezone.now, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("usuario"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    username = models.CharField(_("usuario (texto)"), max_length=150, blank=True)
    property = models.ForeignKey(
        Property,
        verbose_name=_("propiedad"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField(_("acción"), max_length=20, choices=Action.choices, db_index=True)
    object_type = models.CharField(_("tipo de objeto"), max_length=100, blank=True, db_index=True)
    object_id = models.CharField(_("id del objeto"), max_length=64, blank=True)
    object_repr = models.CharField(_("objeto"), max_length=255, blank=True)
    changes = models.JSONField(_("cambios"), default=dict, blank=True, help_text=_("Valor anterior y nuevo."))
    reason = models.CharField(_("motivo"), max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(_("IP"), null=True, blank=True)
    user_agent = models.CharField(_("navegador"), max_length=255, blank=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        verbose_name = _("registro de auditoría")
        verbose_name_plural = _("auditoría")
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return (
            f"{self.timestamp:%d/%m/%Y %H:%M} {self.username} {self.get_action_display()} {self.object_repr}"
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(_("La auditoría no se puede modificar."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("La auditoría no se puede eliminar."))
