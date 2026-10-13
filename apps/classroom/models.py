"""Modo aula (RF-SIM-01 a 05): escenarios guiados, eventos del docente y avance."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import PropertyScopedModel, TimeStampedModel


class ScenarioRun(TimeStampedModel, PropertyScopedModel):
    """RF-SIM-03: un escenario lanzado en un hotel de práctica."""

    scenario = models.CharField(_("escenario"), max_length=30)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    data = models.JSONField(_("datos del escenario"), default=dict, blank=True)
    completed_at = models.DateTimeField(_("completado"), null=True, blank=True)

    class Meta:
        verbose_name = _("escenario lanzado")
        verbose_name_plural = _("escenarios lanzados")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.scenario} · {self.property}"


class PracticeEvent(TimeStampedModel, PropertyScopedModel):
    """RF-SIM-04: evento generado por el docente."""

    kind = models.CharField(_("evento"), max_length=20)
    message = models.CharField(_("detalle"), max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = _("evento de práctica")
        verbose_name_plural = _("eventos de práctica")
        ordering = ["-created_at"]

    def __str__(self):
        return self.message
