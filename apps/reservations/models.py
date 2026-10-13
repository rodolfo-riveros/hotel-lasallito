"""Reservas y grupos (RF-RES-01 a RF-RES-10).

Una reserva ocupa una habitación (o un tipo de habitación si aún no se asignó)
entre `arrival` y `departure` (exclusive). En PostgreSQL una restricción de
exclusión impide que dos reservas activas ocupen la misma habitación en fechas
que se solapan (sección 8.3, RNF-INT-01/02). Ver migración 0002.
"""

import uuid
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, SoftDeleteModel, TimeStampedModel

MONEY = {"max_digits": 12, "decimal_places": 2}


class GroupBlock(TimeStampedModel, SoftDeleteModel, PropertyScopedModel):
    """RF-RES-04: grupo con bloqueo de habitaciones, fecha de liberación y contrato."""

    class Status(models.TextChoices):
        TENTATIVE = "tentative", _("Tentativo")
        DEFINITE = "definite", _("Definitivo")
        RELEASED = "released", _("Liberado")
        CANCELLED = "cancelled", _("Cancelado")

    code = models.CharField(_("código"), max_length=20)
    name = models.CharField(_("nombre del grupo"), max_length=150)
    company = models.ForeignKey(
        "guests.Company", verbose_name=_("empresa / agencia"), null=True, blank=True, on_delete=models.PROTECT
    )
    contact_name = models.CharField(_("contacto"), max_length=150, blank=True)
    contact_email = models.EmailField(_("correo del contacto"), blank=True)
    arrival = models.DateField(_("llegada"))
    departure = models.DateField(_("salida"))
    release_date = models.DateField(
        _("fecha de liberación"), help_text=_("Hasta esta fecha se respeta el bloqueo.")
    )
    rate_plan = models.ForeignKey("rates.RatePlan", verbose_name=_("tarifa"), on_delete=models.PROTECT)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.TENTATIVE)
    contract = models.TextField(_("contrato / condiciones"), blank=True)

    class Meta:
        verbose_name = _("grupo")
        verbose_name_plural = _("grupos")
        ordering = ["-arrival"]

    def __str__(self):
        return f"{self.code} · {self.name}"


class GroupAllotment(models.Model):
    group = models.ForeignKey(GroupBlock, on_delete=models.CASCADE, related_name="allotments")
    room_type = models.ForeignKey("rooms.RoomType", verbose_name=_("tipo"), on_delete=models.PROTECT)
    quantity = models.PositiveSmallIntegerField(_("habitaciones"))
    rate = models.DecimalField(_("tarifa pactada por noche"), null=True, blank=True, **MONEY)

    class Meta:
        verbose_name = _("cupo del grupo")
        verbose_name_plural = _("cupos del grupo")

    def __str__(self):
        return f"{self.quantity} × {self.room_type}"


class Reservation(TimeStampedModel, SoftDeleteModel, PropertyScopedModel):
    class Status(models.TextChoices):
        QUOTE = "quote", _("Cotización")
        WAITLIST = "waitlist", _("Lista de espera")
        PENDING = "pending", _("Pendiente")
        CONFIRMED = "confirmed", _("Confirmada")
        GUARANTEED = "guaranteed", _("Garantizada")
        CHECKED_IN = "checked_in", _("Check-in")
        CHECKED_OUT = "checked_out", _("Check-out")
        NO_SHOW = "no_show", _("No show")
        CANCELLED = "cancelled", _("Cancelada")

    class Channel(models.TextChoices):
        DIRECT = "direct", _("Directo / recepción")
        PHONE = "phone", _("Teléfono / correo")
        WALK_IN = "walk_in", _("Walk-in")
        WEB = "web", _("Web propia")
        BOOKING = "booking", _("Booking.com")
        EXPEDIA = "expedia", _("Expedia")
        AIRBNB = "airbnb", _("Airbnb")
        AGENCY = "agency", _("Agencia / operador")
        CORPORATE = "corporate", _("Empresa")

    class Guarantee(models.TextChoices):
        NONE = "none", _("Sin garantía")
        CARD = "card", _("Tarjeta")
        TRANSFER = "transfer", _("Transferencia")
        YAPE_PLIN = "yape_plin", _("Yape / Plin")
        DEPOSIT = "deposit", _("Depósito")
        CREDIT = "credit", _("Crédito de empresa")

    # Estados que ocupan inventario
    ACTIVE_STATUSES = ("pending", "confirmed", "guaranteed", "checked_in")
    PRE_ARRIVAL_STATUSES = ("pending", "confirmed", "guaranteed")
    OCCUPYING_STATUSES = ("pending", "confirmed", "guaranteed", "checked_in", "checked_out")

    code = models.CharField(_("código"), max_length=20, db_index=True)
    status = models.CharField(_("estado"), max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    channel = models.CharField(_("canal"), max_length=12, choices=Channel.choices, default=Channel.DIRECT)
    external_ref = models.CharField(_("referencia del canal"), max_length=60, blank=True, db_index=True)
    guest = models.ForeignKey(
        "guests.Guest",
        verbose_name=_("huésped titular"),
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    company = models.ForeignKey(
        "guests.Company",
        verbose_name=_("empresa / agencia"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    group = models.ForeignKey(
        GroupBlock,
        verbose_name=_("grupo"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reservations",
    )
    room_type = models.ForeignKey(
        "rooms.RoomType", verbose_name=_("tipo de habitación"), on_delete=models.PROTECT
    )
    room = models.ForeignKey(
        "rooms.Room",
        verbose_name=_("habitación"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    arrival = models.DateField(_("llegada"), db_index=True)
    departure = models.DateField(_("salida"), db_index=True)
    eta = models.TimeField(_("hora estimada de llegada"), null=True, blank=True)
    etd = models.TimeField(_("hora estimada de salida"), null=True, blank=True)
    adults = models.PositiveSmallIntegerField(_("adultos"), default=2)
    children = models.PositiveSmallIntegerField(_("niños"), default=0)
    extra_beds = models.PositiveSmallIntegerField(_("camas extra"), default=0)
    cribs = models.PositiveSmallIntegerField(_("cunas"), default=0)
    rate_plan = models.ForeignKey("rates.RatePlan", verbose_name=_("tarifa"), on_delete=models.PROTECT)
    currency = models.CharField(_("moneda"), max_length=3, default="PEN")
    nightly_rates = models.JSONField(_("tarifa por noche"), default=list, blank=True)
    total_amount = models.DecimalField(_("total del alojamiento"), default=Decimal("0"), **MONEY)
    discount_percent = models.DecimalField(
        _("descuento (%)"), max_digits=5, decimal_places=2, default=Decimal("0")
    )
    discount_reason = models.CharField(_("motivo del descuento"), max_length=150, blank=True)
    promo_code = models.CharField(_("código promocional"), max_length=30, blank=True)
    # RF-RES-09: preferencias
    pref_floor = models.SmallIntegerField(_("piso preferido"), null=True, blank=True)
    pref_view = models.CharField(_("vista preferida"), max_length=20, blank=True)
    pref_quiet = models.BooleanField(_("prefiere zona silenciosa"), default=False)
    pref_accessible = models.BooleanField(_("requiere accesibilidad"), default=False)
    special_requests = models.TextField(_("solicitudes especiales"), blank=True)
    notes = models.TextField(_("notas internas"), blank=True)
    # RF-RES-07
    guarantee = models.CharField(
        _("garantía"), max_length=10, choices=Guarantee.choices, default=Guarantee.NONE
    )
    deposit_required = models.DecimalField(_("depósito requerido"), default=Decimal("0"), **MONEY)
    # Exoneración IGV a no domiciliados (RF-TAR-06, RF-FAC-04)
    igv_exempt = models.BooleanField(
        _("exonerado de IGV (no domiciliado)"),
        default=False,
        help_text=_("Se valida en el check-in con pasaporte y fecha de ingreso al país."),
    )
    # RF-RES-06
    cancelled_at = models.DateTimeField(_("cancelada el"), null=True, blank=True)
    cancellation_reason = models.CharField(_("motivo de cancelación"), max_length=255, blank=True)
    cancellation_penalty = models.DecimalField(_("penalidad"), default=Decimal("0"), **MONEY)
    overbooked = models.BooleanField(_("sobreventa aprobada"), default=False)
    checked_in_at = models.DateTimeField(_("check-in"), null=True, blank=True)
    checked_out_at = models.DateTimeField(_("check-out"), null=True, blank=True)
    # RF-TUR-04: tren y Machu Picchu
    train_date = models.DateField(_("fecha del tren"), null=True, blank=True)
    train_time = models.TimeField(_("hora del tren"), null=True, blank=True)
    machu_picchu_date = models.DateField(_("ingreso a Machu Picchu"), null=True, blank=True)
    portal_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    precheckin_at = models.DateTimeField(_("pre-check-in en línea"), null=True, blank=True)
    language = models.CharField(_("idioma de comunicación"), max_length=5, default="es")

    class Meta:
        verbose_name = _("reserva")
        verbose_name_plural = _("reservas")
        ordering = ["-arrival", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(departure__gt=models.F("arrival")), name="res_dates_valid"
            ),
            models.UniqueConstraint(fields=["property", "code"], name="uniq_reservation_code"),
        ]
        indexes = [models.Index(fields=["property", "status", "arrival"])]

    def __str__(self):
        return f"{self.code} · {self.guest}"

    @property
    def nights(self) -> int:
        return (self.departure - self.arrival).days

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    def nightly_amounts(self) -> list[Decimal]:
        return [Decimal(n["amount"]) for n in self.nightly_rates or []]

    def rate_for(self, day) -> Decimal:
        for n in self.nightly_rates or []:
            if n["date"] == day.isoformat():
                return Decimal(n["amount"])
        amounts = self.nightly_amounts()
        return amounts[-1] if amounts else Decimal("0")

    @property
    def main_folio(self):
        return self.folios.filter(is_main=True).first()

    @property
    def balance(self) -> Decimal:
        if "charges_total" in self.__dict__:  # anotado con folio.queries (sin N+1)
            return self.charges_total - self.payments_total
        return sum((f.balance for f in self.folios.all()), Decimal("0"))

    @property
    def includes_breakfast(self) -> bool:
        return self.rate_plan.includes_breakfast


class WaitlistEntry(TimeStampedModel, PropertyScopedModel):
    """RF-RES-08: solicitudes sin disponibilidad."""

    guest_name = models.CharField(_("huésped"), max_length=150)
    contact = models.CharField(_("contacto"), max_length=150)
    room_type = models.ForeignKey("rooms.RoomType", verbose_name=_("tipo"), on_delete=models.CASCADE)
    arrival = models.DateField(_("llegada"))
    departure = models.DateField(_("salida"))
    adults = models.PositiveSmallIntegerField(_("adultos"), default=2)
    notes = models.TextField(_("notas"), blank=True)
    resolved = models.BooleanField(_("atendida"), default=False)

    class Meta:
        verbose_name = _("lista de espera")
        verbose_name_plural = _("lista de espera")
        ordering = ["arrival"]

    def __str__(self):
        return f"{self.guest_name} {self.arrival:%d/%m}"
