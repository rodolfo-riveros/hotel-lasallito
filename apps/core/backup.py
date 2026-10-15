"""Respaldo lógico de la base y retención de datos personales.

- RNF-DIS-02 / RF-REC-13: copia diaria comprimida de todos los datos del PMS, guardada 30 días
  (`BACKUP_RETENTION_DAYS`) en `BACKUP_DIR` y, si `BACKUP_UPLOAD=true`, también en el almacenamiento
  de archivos (Supabase Storage) como copia fuera del servidor. Se verifica al terminar.
  Restaurar:  python manage.py loaddata <archivo>.json.gz  sobre una base recién migrada.
  Esto complementa (no reemplaza) los respaldos propios de Supabase.
- RNF-SEG-06 (Ley 29733): anonimiza huéspedes sin estadías ni reservas en `GUEST_RETENTION_YEARS`.
"""

import gzip
import io
import json
import logging
import threading
from datetime import timedelta
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import management
from django.db import close_old_connections
from django.utils import timezone

log = logging.getLogger(__name__)

EXCLUDE = ["sessions", "admin.logentry", "axes", "contenttypes", "auth.permission"]


def backup_dir() -> Path:
    path = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup() -> Path:
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    target = backup_dir() / f"pms-{stamp}.json.gz"
    buf = io.StringIO()
    management.call_command("dumpdata", exclude=EXCLUDE, natural_foreign=True, stdout=buf, verbosity=0)
    with gzip.open(target, "wt", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    count = verify(target)
    log.info("Respaldo %s con %s registros", target.name, count)
    if getattr(settings, "BACKUP_UPLOAD", False):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        default_storage.save(f"backups/{target.name}", ContentFile(target.read_bytes()))
    purge_old()
    return target


def verify(path: Path) -> int:
    """Prueba de lectura: el archivo se descomprime y es JSON válido. Devuelve cuántos registros tiene."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("Respaldo inválido")
    return len(data)


def purge_old() -> int:
    days = getattr(settings, "BACKUP_RETENTION_DAYS", 30)
    limit = timezone.now().timestamp() - days * 86400
    removed = 0
    for f in backup_dir().glob("pms-*.json.gz"):
        if f.stat().st_mtime < limit:
            f.unlink()
            removed += 1
    return removed


def latest_backup() -> Path | None:
    files = sorted(backup_dir().glob("pms-*.json.gz"))
    return files[-1] if files else None


def backup_in_background():
    """El cierre de día no espera al respaldo (contra Supabase toma minutos)."""

    def target():
        close_old_connections()
        try:
            create_backup()
        except Exception:  # noqa: BLE001 - se registra y se reintenta en el próximo ciclo
            log.exception("Falló el respaldo automático")
        finally:
            close_old_connections()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def expire_guest_data(today=None) -> int:
    """RNF-SEG-06: conservación limitada. Anonimiza a quien no se hospeda hace N años."""
    from apps.guests.services import anonymize

    Guest = apps.get_model("guests", "Guest")
    Reservation = apps.get_model("reservations", "Reservation")
    years = getattr(settings, "GUEST_RETENTION_YEARS", 5)
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=365 * years)
    recent = Reservation.all_objects.filter(departure__gte=cutoff).values("guest_id")
    stale = (
        Guest.objects.filter(created_at__date__lt=cutoff)
        .exclude(first_name="Anonimizado")
        .exclude(pk__in=recent)
    )
    count = 0
    for guest in stale.iterator():
        anonymize(guest, f"conservación vencida ({years} años sin estadías)")
        count += 1
    return count
