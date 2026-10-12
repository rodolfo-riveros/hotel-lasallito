"""Portal del huésped, encuestas y libro de reclamaciones (RF-POR-01 a 03, RF-HUE-05)."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel

SCORE = [MinValueValidator(1), MaxValueValidator(5)]


class ServiceRequest(TimeStampedModel, PropertyScopedModel):
    """RF-POR-02: el huésped pide servicios desde su celular."""

    class Kind(models.TextChoices):
        TOWELS = "towels", _("Toallas o amenities")
        OXYGEN = "oxygen", _("Oxígeno")
        WAKEUP = "wakeup", _("Despertador")
        TRANSFER = "transfer", _("Traslado")
        CLEANING = "cleaning", _("Limpieza de habitación")
        MAINTENANCE = "maintenance", _("Algo no funciona")
        OTHER = "other", _("Otro")

    class Status(models.TextChoices):
        NEW = "new", _("Recibido")
        IN_PROGRESS = "in_progress", _("En atención")
        DONE = "done", _("Atendido")
        CANCELLED = "cancelled", _("Cancelado")

    reservation = models.ForeignKey("reservations.Reservation", on_delete=models.CASCADE, related_name="requests")
    kind = models.CharField(_("tipo"), max_length=15, choices=Kind.choices)
    notes = models.CharField(_("detalle"), max_length=255, blank=True)
    requested_for = models.DateTimeField(_("para"), null=True, blank=True)
    status = models.CharField(_("estado"), max_length=12, choices=Status.choices, default=Status.NEW)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")

    class Meta:
        verbose_name = _("solicitud de servicio")
        verbose_name_plural = _("solicitudes de huéspedes")
        ordering = ["status", "-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.reservation.room or self.reservation.code}"


class Survey(TimeStampedModel):
    """RF-HUE-05 / RF-REC-10: encuesta de salida."""

    reservation = models.OneToOneField("reservations.Reservation", on_delete=models.CASCADE, related_name="survey")
    overall = models.PositiveSmallIntegerField(_("experiencia general"), validators=SCORE)
    room = models.PositiveSmallIntegerField(_("habitación"), validators=SCORE)
    cleanliness = models.PositiveSmallIntegerField(_("limpieza"), validators=SCORE)
    service = models.PositiveSmallIntegerField(_("atención"), validators=SCORE)
    breakfast = models.PositiveSmallIntegerField(_("desayuno"), validators=SCORE, null=True, blank=True)
    would_recommend = models.BooleanField(_("nos recomendaría"), default=True)
    comments = models.TextField(_("comentarios"), blank=True)

    class Meta:
        verbose_name = _("encuesta")
        verbose_name_plural = _("encuestas")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Encuesta {self.reservation.code}: {self.overall}/5"

    @property
    def average(self):
        scores = [s for s in (self.overall, self.room, self.cleanliness, self.service, self.breakfast) if s]
        return round(sum(scores) / len(scores), 1)


class Complaint(TimeStampedModel, PropertyScopedModel):
    """Libro de reclamaciones virtual (Código de Protección al Consumidor) y quejas (RF-HUE-05)."""

    class Kind(models.TextChoices):
        CLAIM = "reclamo", _("Reclamo (disconformidad con el servicio)")
        COMPLAINT = "queja", _("Queja (malestar en la atención)")

    class Status(models.TextChoices):
        OPEN = "open", _("Registrado")
        IN_REVIEW = "in_review", _("En revisión")
        ANSWERED = "answered", _("Respondido")
        CLOSED = "closed", _("Cerrado")

    number = models.CharField(_("número"), max_length=20)
    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices, default=Kind.CLAIM)
    full_name = models.CharField(_("nombre completo"), max_length=150)
    doc_number = models.CharField(_("documento"), max_length=20)
    email = models.EmailField(_("correo"))
    phone = models.CharField(_("teléfono"), max_length=30, blank=True)
    address = models.CharField(_("domicilio"), max_length=255, blank=True)
    reservation = models.ForeignKey("reservations.Reservation", null=True, blank=True, on_delete=models.SET_NULL)
    amount = models.DecimalField(_("monto reclamado"), max_digits=10, decimal_places=2, null=True, blank=True)
    description = models.TextField(_("detalle"))
    request = models.TextField(_("pedido del consumidor"))
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.OPEN)
    response = models.TextField(_("respuesta del proveedor"), blank=True)
    responded_at = models.DateTimeField(_("respondido el"), null=True, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        verbose_name = _("reclamo")
        verbose_name_plural = _("libro de reclamaciones")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} · {self.full_name}"

    @property
    def due_date(self):
        from datetime import timedelta

        return (self.created_at + timedelta(days=15)).date()
