"""Tours, traslados y servicios externos (RF-TUR-01 a 05)."""

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

MONEY = {"max_digits": 10, "decimal_places": 2}


class Operator(TimeStampedModel, PropertyScopedModel):
    name = models.CharField(_("operador"), max_length=150)
    ruc = models.CharField(_("RUC"), max_length=11, blank=True)
    contact_name = models.CharField(_("contacto"), max_length=150, blank=True)
    email = models.EmailField(_("correo para la agenda"), blank=True)
    phone = models.CharField(_("teléfono / WhatsApp"), max_length=30, blank=True)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("operador")
        verbose_name_plural = _("operadores")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Service(TimeStampedModel, PropertyScopedModel):
    """RF-TUR-01: catálogo de tours y traslados."""

    class Kind(models.TextChoices):
        CITY_TOUR = "city_tour", _("City tour Cusco")
        SACRED_VALLEY = "sacred_valley", _("Valle Sagrado")
        MACHU_PICCHU = "machu_picchu", _("Machu Picchu")
        RAINBOW = "rainbow", _("Montaña de Colores")
        AIRPORT = "airport", _("Traslado aeropuerto")
        TRAIN = "train", _("Traslado estación de tren")
        OTHER = "other", _("Otro")

    kind = models.CharField(_("tipo"), max_length=15, choices=Kind.choices, default=Kind.OTHER)
    name = models.CharField(_("nombre"), max_length=150)
    name_en = models.CharField(_("nombre (inglés)"), max_length=150, blank=True)
    name_pt = models.CharField(_("nombre (portugués)"), max_length=150, blank=True)
    description = models.TextField(_("descripción"), blank=True)
    operator = models.ForeignKey(
        Operator, verbose_name=_("operador"), null=True, blank=True, on_delete=models.SET_NULL
    )
    price = models.DecimalField(_("precio por persona (con IGV)"), **MONEY)
    cost = models.DecimalField(_("costo por persona"), default=Decimal("0"), **MONEY)
    pickup_time = models.TimeField(_("hora de recojo habitual"), null=True, blank=True)
    duration_hours = models.DecimalField(
        _("duración (horas)"), max_digits=4, decimal_places=1, default=Decimal("4")
    )
    is_public = models.BooleanField(_("ofrecer en la web"), default=True)
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("servicio")
        verbose_name_plural = _("tours y traslados")
        ordering = ["kind", "name"]

    def __str__(self):
        return f"{self.name} ({self.price})"

    @property
    def is_transfer(self):
        return self.kind in (self.Kind.AIRPORT, self.Kind.TRAIN)


class ServiceBooking(TimeStampedModel, PropertyScopedModel):
    """RF-TUR-02/03: venta desde el folio y agenda de recojos."""

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Solicitado")
        CONFIRMED = "confirmed", _("Confirmado con el operador")
        DONE = "done", _("Realizado")
        CANCELLED = "cancelled", _("Anulado")

    service = models.ForeignKey(
        Service, verbose_name=_("servicio"), on_delete=models.PROTECT, related_name="bookings"
    )
    reservation = models.ForeignKey(
        "reservations.Reservation",
        verbose_name=_("reserva"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_bookings",
    )
    guest_name = models.CharField(_("pasajero"), max_length=150)
    date = models.DateField(_("fecha"))
    pickup_time = models.TimeField(_("hora de recojo"), null=True, blank=True)
    pickup_point = models.CharField(_("punto de recojo"), max_length=150, default="Lobby del hotel")
    pax = models.PositiveSmallIntegerField(_("pasajeros"), default=1)
    unit_price = models.DecimalField(_("precio por persona"), **MONEY)
    unit_cost = models.DecimalField(_("costo por persona"), **MONEY)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.REQUESTED)
    charge = models.ForeignKey(
        "folio.Charge", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notes = models.CharField(_("notas (vuelo, tren, dieta)"), max_length=255, blank=True)
    sent_to_operator_at = models.DateTimeField(_("enviado al operador"), null=True, blank=True)

    class Meta:
        verbose_name = _("venta de servicio")
        verbose_name_plural = _("ventas de servicios")
        ordering = ["date", "pickup_time"]

    def __str__(self):
        return f"{self.service.name} · {self.guest_name} · {self.date:%d/%m}"

    @property
    def total(self):
        return self.unit_price * self.pax

    @property
    def total_cost(self):
        return self.unit_cost * self.pax
