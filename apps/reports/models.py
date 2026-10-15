"""Envío programado de reportes por correo (RF-REP-06)."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class ReportSubscription(TimeStampedModel, PropertyScopedModel):
    class Frequency(models.TextChoices):
        DAILY = "daily", _("Diario (día anterior)")
        WEEKLY = "weekly", _("Semanal, lunes (semana anterior)")
        MONTHLY = "monthly", _("Mensual, día 1 (mes anterior)")

    class Format(models.TextChoices):
        PDF = "pdf", "PDF"
        XLSX = "xlsx", "Excel"
        CSV = "csv", "CSV"

    report = models.CharField(_("reporte"), max_length=20)
    recipients = models.CharField(
        _("destinatarios"), max_length=500, help_text=_("Correos separados por coma")
    )
    frequency = models.CharField(
        _("frecuencia"), max_length=8, choices=Frequency.choices, default=Frequency.DAILY
    )
    format = models.CharField(_("formato"), max_length=4, choices=Format.choices, default=Format.PDF)
    is_active = models.BooleanField(_("activo"), default=True)
    last_sent_on = models.DateField(_("último envío"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("envío programado")
        verbose_name_plural = _("envíos programados")
        ordering = ["report"]

    def __str__(self):
        return f"{self.report} · {self.get_frequency_display()}"

    @property
    def emails(self) -> list[str]:
        return [e.strip() for e in self.recipients.replace(";", ",").split(",") if e.strip()]
