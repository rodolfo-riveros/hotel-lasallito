"""Planes de tarifa, temporadas, restricciones y políticas (RF-TAR-01 a RF-TAR-05, RF-RES-06)."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}
PERCENT = {
    "max_digits": 5,
    "decimal_places": 2,
    "validators": [MinValueValidator(Decimal("-100")), MaxValueValidator(Decimal("100"))],
}


class CancellationPolicy(TimeStampedModel, PropertyScopedModel):
    """RF-RES-06: gratis hasta X días, penalidad de una noche, porcentaje o no reembolsable."""

    class Penalty(models.TextChoices):
        NONE = "none", _("Sin penalidad")
        FIRST_NIGHT = "first_night", _("Primera noche")
        PERCENT = "percent", _("Porcentaje del total")
        FULL = "full", _("Total de la estadía")

    name = models.CharField(_("nombre"), max_length=100)
    free_until_days = models.PositiveSmallIntegerField(_("cancelación gratis hasta (días antes)"), default=2)
    penalty = models.CharField(
        _("penalidad"), max_length=20, choices=Penalty.choices, default=Penalty.FIRST_NIGHT
    )
    penalty_percent = models.DecimalField(_("porcentaje"), default=Decimal("0"), **PERCENT)
    no_show_penalty = models.CharField(
        _("penalidad por no show"), max_length=20, choices=Penalty.choices, default=Penalty.FIRST_NIGHT
    )
    is_non_refundable = models.BooleanField(_("no reembolsable"), default=False)
    description = models.TextField(_("texto para el huésped"), blank=True)
    description_en = models.TextField(_("texto (inglés)"), blank=True)
    description_pt = models.TextField(_("texto (portugués)"), blank=True)

    class Meta:
        verbose_name = _("política de cancelación")
        verbose_name_plural = _("políticas de cancelación")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def _amount(self, kind, nightly: list[Decimal], total: Decimal) -> Decimal:
        if kind == self.Penalty.FIRST_NIGHT:
            return nightly[0] if nightly else Decimal("0")
        if kind == self.Penalty.PERCENT:
            return (total * self.penalty_percent / 100).quantize(Decimal("0.01"))
        if kind == self.Penalty.FULL:
            return total
        return Decimal("0")

    def cancellation_penalty(self, arrival, cancel_date, nightly: list[Decimal], total: Decimal) -> Decimal:
        """Cargo por cancelar en `cancel_date` una reserva que llega en `arrival`."""
        if self.is_non_refundable:
            return total
        if (arrival - cancel_date).days >= self.free_until_days:
            return Decimal("0")
        return self._amount(self.penalty, nightly, total)

    def no_show_charge(self, nightly: list[Decimal], total: Decimal) -> Decimal:
        if self.is_non_refundable:
            return total
        return self._amount(self.no_show_penalty, nightly, total)


class RatePlan(TimeStampedModel, PropertyScopedModel):
    """RF-TAR-01: planes de tarifa. RF-TAR-04: plan de alimentación."""

    class Kind(models.TextChoices):
        RACK = "rack", _("Rack")
        CORPORATE = "corporate", _("Corporativa")
        AGENCY = "agency", _("Agencia (neta)")
        PACKAGE = "package", _("Paquete")
        PROMO = "promo", _("Promoción")
        RESIDENT = "resident", _("Residente peruano")
        NON_REFUNDABLE = "non_refundable", _("No reembolsable")
        LONG_STAY = "long_stay", _("Estadía larga")

    class MealPlan(models.TextChoices):
        ROOM_ONLY = "RO", _("Solo alojamiento")
        BREAKFAST = "BB", _("Desayuno incluido")
        HALF_BOARD = "HB", _("Media pensión")
        FULL_BOARD = "FB", _("Pensión completa")

    code = models.SlugField(_("código"), max_length=20)
    name = models.CharField(_("nombre"), max_length=100)
    name_en = models.CharField(_("nombre (inglés)"), max_length=100, blank=True)
    name_pt = models.CharField(_("nombre (portugués)"), max_length=100, blank=True)
    kind = models.CharField(_("tipo"), max_length=20, choices=Kind.choices, default=Kind.RACK)
    meal_plan = models.CharField(
        _("plan de alimentación"), max_length=2, choices=MealPlan.choices, default="BB"
    )
    currency = models.ForeignKey(
        "core.Currency", verbose_name=_("moneda"), on_delete=models.PROTECT, related_name="+", default="PEN"
    )
    base_plan = models.ForeignKey(
        "self",
        verbose_name=_("derivada de"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derived_plans",
        help_text=_("Si se indica, el precio sale del plan base con el ajuste porcentual."),
    )
    adjustment_percent = models.DecimalField(
        _("ajuste sobre el plan base (%)"),
        default=Decimal("0"),
        help_text=_("Ej. -10 = 10% menos"),
        **PERCENT,
    )
    cancellation_policy = models.ForeignKey(
        CancellationPolicy,
        verbose_name=_("política de cancelación"),
        on_delete=models.PROTECT,
        related_name="+",
    )
    min_nights = models.PositiveSmallIntegerField(_("mínimo de noches"), default=1)
    commission_percent = models.DecimalField(_("comisión (%)"), default=Decimal("0"), **PERCENT)
    is_public = models.BooleanField(_("visible en la web"), default=True)
    requires_peruvian_resident = models.BooleanField(_("solo residentes peruanos"), default=False)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("plan de tarifa")
        verbose_name_plural = _("planes de tarifa")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_rateplan_code")]

    def __str__(self):
        return self.name

    @property
    def includes_breakfast(self):
        return self.meal_plan != self.MealPlan.ROOM_ONLY


class Season(TimeStampedModel, PropertyScopedModel):
    """RF-TAR-02: temporadas alta, media, baja y fechas especiales."""

    class Kind(models.TextChoices):
        HIGH = "high", _("Alta")
        MID = "mid", _("Media")
        LOW = "low", _("Baja")
        SPECIAL = "special", _("Fecha especial")

    name = models.CharField(_("nombre"), max_length=100)
    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices, default=Kind.HIGH)
    start_date = models.DateField(_("desde"))
    end_date = models.DateField(_("hasta (inclusive)"))
    priority = models.PositiveSmallIntegerField(
        _("prioridad"), default=1, help_text=_("Si dos temporadas se cruzan, gana la de mayor prioridad.")
    )
    min_nights = models.PositiveSmallIntegerField(_("mínimo de noches"), default=1)

    class Meta:
        verbose_name = _("temporada")
        verbose_name_plural = _("temporadas")
        ordering = ["start_date"]

    def __str__(self):
        return f"{self.name} ({self.start_date:%d/%m/%Y}–{self.end_date:%d/%m/%Y})"


class RatePrice(TimeStampedModel, PropertyScopedModel):
    """Precio por noche de un tipo de habitación en un plan (y temporada).

    RF-TAR-05: suplementos por adulto adicional, niño, cama extra y cuna.
    Sin temporada = precio de todo el año.
    """

    rate_plan = models.ForeignKey(
        RatePlan, verbose_name=_("plan"), on_delete=models.CASCADE, related_name="prices"
    )
    room_type = models.ForeignKey(
        "rooms.RoomType",
        verbose_name=_("tipo de habitación"),
        on_delete=models.CASCADE,
        related_name="prices",
    )
    season = models.ForeignKey(
        Season,
        verbose_name=_("temporada"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="prices",
    )
    price = models.DecimalField(_("precio por noche"), **MONEY)
    extra_adult = models.DecimalField(_("adulto adicional"), default=Decimal("0"), **MONEY)
    child = models.DecimalField(_("niño"), default=Decimal("0"), **MONEY)
    extra_bed = models.DecimalField(_("cama extra"), default=Decimal("0"), **MONEY)
    crib = models.DecimalField(_("cuna"), default=Decimal("0"), **MONEY)

    class Meta:
        verbose_name = _("precio")
        verbose_name_plural = _("precios")
        ordering = ["rate_plan", "room_type", "season"]
        constraints = [
            models.UniqueConstraint(fields=["rate_plan", "room_type", "season"], name="uniq_rate_price"),
        ]

    def __str__(self):
        return f"{self.rate_plan} · {self.room_type} · {self.season or 'todo el año'}: {self.price}"


class DateRestriction(TimeStampedModel, PropertyScopedModel):
    """RF-TAR-02: mínimo de noches y días de entrada o salida restringidos por fecha."""

    date_from = models.DateField(_("desde"))
    date_to = models.DateField(_("hasta (inclusive)"))
    room_type = models.ForeignKey(
        "rooms.RoomType",
        verbose_name=_("tipo (vacío = todos)"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    rate_plan = models.ForeignKey(
        RatePlan, verbose_name=_("plan (vacío = todos)"), null=True, blank=True, on_delete=models.CASCADE
    )
    min_nights = models.PositiveSmallIntegerField(_("mínimo de noches"), null=True, blank=True)
    closed_to_arrival = models.BooleanField(_("cerrado a llegadas"), default=False)
    closed_to_departure = models.BooleanField(_("cerrado a salidas"), default=False)
    stop_sell = models.BooleanField(_("cerrado a la venta"), default=False)
    reason = models.CharField(_("motivo"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("restricción por fecha")
        verbose_name_plural = _("restricciones por fecha")
        ordering = ["date_from"]

    def __str__(self):
        return f"{self.date_from:%d/%m/%Y}–{self.date_to:%d/%m/%Y} {self.reason}"


class Promotion(TimeStampedModel, PropertyScopedModel):
    """RF-WEB-04: códigos promocionales."""

    code = models.CharField(_("código"), max_length=30)
    name = models.CharField(_("nombre"), max_length=100)
    discount_percent = models.DecimalField(_("descuento (%)"), **PERCENT)
    valid_from = models.DateField(_("válido desde"))
    valid_to = models.DateField(_("válido hasta"))
    stay_from = models.DateField(_("estadías desde"), null=True, blank=True)
    stay_to = models.DateField(_("estadías hasta"), null=True, blank=True)
    min_nights = models.PositiveSmallIntegerField(_("mínimo de noches"), default=1)
    max_uses = models.PositiveIntegerField(_("usos máximos"), null=True, blank=True)
    uses = models.PositiveIntegerField(_("usos"), default=0, editable=False)
    rate_plans = models.ManyToManyField(RatePlan, verbose_name=_("planes (vacío = todos)"), blank=True)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("promoción")
        verbose_name_plural = _("promociones")
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="uniq_promo_code")]

    def __str__(self):
        return f"{self.code} ({self.discount_percent}%)"
