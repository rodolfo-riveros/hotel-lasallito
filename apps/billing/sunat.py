"""Adaptadores SUNAT (patrón adaptador, sección 9).

`SUNAT_MODE=simulator` usa `SimulatorAdapter`: acepta de forma ficticia y deja
al docente activar caídas de conexión o rechazos (sección 12). Para facturar
de verdad se implementa `OSEAdapter` (Nubefact, Efact...) sin tocar el resto.
"""

import hashlib
from dataclasses import dataclass

from django.conf import settings


@dataclass
class SunatResult:
    accepted: bool
    code: str = ""
    message: str = ""
    connection_error: bool = False
    ticket: str = ""


class SunatAdapter:
    def send(self, invoice) -> SunatResult:  # pragma: no cover - interfaz
        raise NotImplementedError

    def void(self, invoice, reason: str) -> SunatResult:  # pragma: no cover - interfaz
        raise NotImplementedError

    def daily_summary(self, property_obj, day, invoices) -> SunatResult:  # pragma: no cover - interfaz
        raise NotImplementedError


class SimulatorAdapter(SunatAdapter):
    """Respuesta ficticia de SUNAT. Nada sale del sistema."""

    def _settings(self, property_obj):
        from .models import SimulationSettings

        sim, _created = SimulationSettings.objects.get_or_create(property=property_obj)
        return sim

    def send(self, invoice) -> SunatResult:
        sim = self._settings(invoice.property)
        if sim.connection_down:
            return SunatResult(False, "0109", "Simulación: sin conexión con SUNAT/OSE", connection_error=True)
        if sim.reject_next > 0:
            sim.reject_next -= 1
            sim.save(update_fields=["reject_next"])
            code, _sep, msg = sim.reject_message.partition(" - ")
            return SunatResult(False, code or "2800", msg or sim.reject_message)
        return SunatResult(
            True,
            "0",
            f"Simulación: La {invoice.get_doc_type_display()} {invoice.full_number} ha sido aceptada",
        )

    def void(self, invoice, reason: str) -> SunatResult:
        sim = self._settings(invoice.property)
        if sim.connection_down:
            return SunatResult(False, "0109", "Simulación: sin conexión con SUNAT/OSE", connection_error=True)
        ticket = hashlib.sha1(f"baja{invoice.pk}".encode()).hexdigest()[:15]  # noqa: S324
        return SunatResult(True, "0", "Simulación: comunicación de baja aceptada", ticket=ticket)

    def daily_summary(self, property_obj, day, invoices) -> SunatResult:
        sim = self._settings(property_obj)
        if sim.connection_down:
            return SunatResult(False, "0109", "Simulación: sin conexión con SUNAT/OSE", connection_error=True)
        ticket = hashlib.sha1(f"rc{property_obj.pk}{day}".encode()).hexdigest()[:15]  # noqa: S324
        return SunatResult(True, "0", f"Simulación: resumen diario {day:%d/%m/%Y} aceptado", ticket=ticket)


class OSEAdapter(SunatAdapter):
    """Conexión real con un OSE/PSE. Se implementa al pasar a producción."""

    def send(self, invoice):
        raise NotImplementedError("Configure el OSE/PSE (Nubefact, Efact...) para SUNAT_MODE=production.")

    void = daily_summary = send


def get_adapter() -> SunatAdapter:
    return OSEAdapter() if settings.SUNAT_MODE == "production" else SimulatorAdapter()


def lookup_ruc(ruc: str):
    """Consulta RUC simulada contra el padrón local ficticio."""
    from .models import FakeTaxpayer

    return FakeTaxpayer.objects.filter(ruc=ruc).first()


def lookup_dni(dni: str):
    from .models import FakePerson

    return FakePerson.objects.filter(dni=dni).first()
