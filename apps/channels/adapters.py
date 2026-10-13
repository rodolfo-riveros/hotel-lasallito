"""Adaptadores del channel manager (sección 9: SiteMinder, Cloudbeds u otro).

`CHANNEL_MANAGER=test` usa `TestChannelManager`: guarda lo publicado en
`ChannelInventory` y permite simular reservas entrantes, como el entorno de
pruebas de un proveedor real. Un adaptador real implementa la misma interfaz.
"""

from dataclasses import dataclass

from django.conf import settings


@dataclass
class PushResult:
    ok: bool
    message: str = ""


class ChannelManagerAdapter:
    def push(self, channel, rows: list[dict]) -> PushResult:  # pragma: no cover - interfaz
        raise NotImplementedError

    def fetch_reservations(self, channel) -> list[dict]:  # pragma: no cover - interfaz
        raise NotImplementedError


class TestChannelManager(ChannelManagerAdapter):
    """Entorno de pruebas: acepta todo salvo que el canal esté desconectado."""

    def push(self, channel, rows):
        from .models import ChannelInventory

        if not channel.is_active:
            return PushResult(False, "Canal desconectado (simulación de error 503)")
        for row in rows:
            ChannelInventory.objects.update_or_create(
                channel=channel,
                room_type_id=row["room_type_id"],
                date=row["date"],
                defaults={
                    "available": row["available"],
                    "price": row.get("price"),
                    "closed": row["available"] <= 0,
                },
            )
        return PushResult(True, f"{len(rows)} fechas publicadas")

    def fetch_reservations(self, channel):
        return []


class SiteMinderAdapter(ChannelManagerAdapter):
    def push(self, channel, rows):
        raise NotImplementedError(
            "Configure las credenciales de SiteMinder (pmsXchange) para usar este adaptador."
        )

    fetch_reservations = push


ADAPTERS = {"test": TestChannelManager, "siteminder": SiteMinderAdapter}


def get_adapter() -> ChannelManagerAdapter:
    return ADAPTERS.get(getattr(settings, "CHANNEL_MANAGER", "test"), TestChannelManager)()
