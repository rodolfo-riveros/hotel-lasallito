"""Pagos en línea (RF-WEB-03, RF-POR-01, RF-CAJ-02 "enlace de pago").

Los datos de tarjeta nunca pasan por el sistema (RNF-SEG-04): el huésped paga
en la página de la pasarela y aquí solo se guarda el resultado (token, últimos
4 dígitos y autorización).
"""

import uuid
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class OnlinePayment(TimeStampedModel, PropertyScopedModel):
    class Status(models.TextChoices):
        CREATED = "created", _("Pendiente")
        PAID = "paid", _("Pagado")
        FAILED = "failed", _("Rechazado")
        CANCELLED = "cancelled", _("Cancelado")

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider = models.CharField(_("pasarela"), max_length=20, default="test")
    reservation = models.ForeignKey(
        "reservations.Reservation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="online_payments",
    )
    folio = models.ForeignKey(
        "folio.Folio", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    amount = models.DecimalField(_("monto"), max_digits=12, decimal_places=2)
    currency = models.CharField(_("moneda"), max_length=3, default="PEN")
    description = models.CharField(_("concepto"), max_length=200)
    email = models.EmailField(_("correo"), blank=True)
    status = models.CharField(_("estado"), max_length=10, choices=Status.choices, default=Status.CREATED)
    provider_reference = models.CharField(_("referencia de la pasarela"), max_length=80, blank=True)
    card_last4 = models.CharField(_("tarjeta"), max_length=4, blank=True)
    card_brand = models.CharField(_("marca"), max_length=20, blank=True)
    error = models.CharField(_("error"), max_length=200, blank=True)
    return_url = models.CharField(max_length=300, blank=True)
    is_deposit = models.BooleanField(_("adelanto"), default=False)

    class Meta:
        verbose_name = _("pago en línea")
        verbose_name_plural = _("pagos en línea")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} {self.amount} {self.get_status_display()}"

    @property
    def amount_display(self) -> Decimal:
        return self.amount
