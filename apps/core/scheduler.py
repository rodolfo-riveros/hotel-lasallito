"""Tareas periódicas del PMS (RF-COMU-02, RNF-DIS-04, RF-MAN-02, RF-ALM-05/07, RF-RES-04).

Se ejecutan con `python manage.py run_scheduler` (programarlo cada 15 minutos con el
Programador de tareas de Windows o cron) o con Celery beat si hay Redis. Cada tarea
es idempotente: correrla dos veces no duplica envíos ni órdenes.
"""

import logging

from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)


def _once_per_day(key: str) -> bool:
    """True la primera vez del día para esa clave (evita repetir avisos diarios)."""
    today = timezone.localdate().isoformat()
    full = f"pms:sched:{key}:{today}"
    if cache.get(full):
        return False
    cache.set(full, True, 60 * 60 * 26)
    return True


def run_all(property_obj) -> dict:
    from apps.billing.services import retry_pending
    from apps.comms.services import notify_role, send_reminders
    from apps.inventory.services import expiring_lots, low_stock
    from apps.maintenance.services import generate_preventive
    from apps.reservations.models import GroupBlock

    result = {}
    result["recordatorios_48h"] = send_reminders(property_obj, property_obj.current_business_date())
    result["sunat_reenviados"] = retry_pending(property_obj)
    result["preventivos"] = len(generate_preventive(property_obj))
    released = GroupBlock.objects.filter(
        property=property_obj,
        status__in=["tentative", "definite"],
        release_date__lt=property_obj.current_business_date(),
    ).update(status=GroupBlock.Status.RELEASED)
    result["grupos_liberados"] = released
    if _once_per_day(f"stock:{property_obj.pk}"):
        low = low_stock(property_obj).count()
        expiring = expiring_lots(property_obj).count()
        if low or expiring:
            notify_role(
                property_obj,
                "storekeeper",
                "Revisión diaria del almacén",
                f"{low} artículos bajo mínimo · {expiring} lotes por vencer",
                url="/almacen/alertas/",
            )
        result["alertas_almacen"] = low + expiring
    result["canales"] = _push_channels(property_obj)
    from apps.core.backup import create_backup, expire_guest_data
    from apps.reports.schedule import send_due

    if _once_per_day("backup"):
        result["respaldo"] = create_backup().name
    if timezone.localdate().day == 1 and _once_per_day("retencion"):
        result["huespedes_anonimizados"] = expire_guest_data()

    result["reportes_enviados"] = send_due(property_obj)
    if timezone.localtime().hour >= 18 and _once_per_day(f"tours:{property_obj.pk}"):
        result["agendas_tours"] = _send_tour_agendas(property_obj)
    log.info("Programador %s: %s", property_obj.code, result)
    return result


def _push_channels(property_obj) -> int:
    """RF-CHA-01: publica en los canales si hubo cambios o si pasó una hora desde la última vez.

    La marca de "cambios pendientes" vive en la caché del proceso web; el programador corre
    en otro proceso, por eso además se publica al menos una vez por hora.
    """
    from datetime import timedelta

    from apps.channels.models import Channel
    from apps.channels.services import is_dirty, push_all

    channels = Channel.objects.filter(property=property_obj, is_active=True)
    hour_ago = timezone.now() - timedelta(hours=1)
    stale = (
        channels.filter(last_sync_at__isnull=True).exists()
        or channels.filter(last_sync_at__lt=hour_ago).exists()
    )
    if not channels.exists() or not (is_dirty(property_obj) or stale):
        return 0
    return len(push_all(property_obj))


def _send_tour_agendas(property_obj) -> int:
    """RF-TUR-03: a partir de las 18:00 envía a cada operador la agenda de recojos de mañana."""
    from datetime import timedelta

    from apps.tours.models import Operator
    from apps.tours.services import send_agenda

    tomorrow = property_obj.current_business_date() + timedelta(days=1)
    return sum(
        send_agenda(property_obj, tomorrow, op)
        for op in Operator.objects.filter(property=property_obj, is_active=True).exclude(email="")
    )
