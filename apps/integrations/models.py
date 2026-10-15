"""Integraciones opcionales de la fase 4: cerraduras electrónicas y central telefónica (PBX)."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class KeyCard(TimeStampedModel, PropertyScopedModel):
    """Tarjeta de habitación grabada en el codificador de la cerradura."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Activa")
        REVOKED = "revoked", _("Anulada")

    reservation = models.ForeignKey(
        "reservations.Reservation", on_delete=models.CASCADE, related_name="key_cards"
    )
    room = models.ForeignKey("rooms.Room", on_delete=models.PROTECT, related_name="+")
    card_ref = models.CharField(_("referencia de la tarjeta"), max_length=60)
    valid_from = models.DateTimeField(_("válida desde"))
    valid_to = models.DateTimeField(_("válida hasta"))
    status = models.CharField(_("estado"), max_length=8, choices=Status.choices, default=Status.ACTIVE)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider = models.CharField(_("cerradura"), max_length=20)

    class Meta:
        verbose_name = _("tarjeta de habitación")
        verbose_name_plural = _("tarjetas de habitación")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.room.number} · {self.card_ref}"


class CallRecord(TimeStampedModel, PropertyScopedModel):
    """Llamada registrada por la central (CDR) y su cargo en el folio."""

    class Kind(models.TextChoices):
        INTERNAL = "internal", _("Interna")
        LOCAL = "local", _("Local / fijo")
        MOBILE = "mobile", _("Celular")
        NATIONAL = "national", _("Nacional")
        INTERNATIONAL = "international", _("Internacional")

    external_id = models.CharField(_("id en la central"), max_length=64)
    extension = models.CharField(_("anexo"), max_length=10)
    room = models.ForeignKey("rooms.Room", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reservation = models.ForeignKey(
        "reservations.Reservation", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls"
    )
    dialed = models.CharField(_("número marcado"), max_length=30)
    kind = models.CharField(_("tipo"), max_length=14, choices=Kind.choices)
    started_at = models.DateTimeField(_("inicio"))
    seconds = models.PositiveIntegerField(_("duración (s)"))
    cost = models.DecimalField(_("importe"), max_digits=10, decimal_places=2, default=Decimal("0"))
    charge = models.ForeignKey(
        "folio.Charge", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = _("llamada")
        verbose_name_plural = _("llamadas")
        ordering = ["-started_at"]
        constraints = [models.UniqueConstraint(fields=["property", "external_id"], name="uniq_call_external")]

    def __str__(self):
        return f"{self.extension} → {self.dialed} ({self.seconds}s)"
