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
    log.info("Programador %s: %s", property_obj.code, result)
    return result
