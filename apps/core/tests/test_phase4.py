"""Fase 4: PWA, respaldo, retención de datos, historial masivo y registros estructurados.

RNF-DIS-02/03, RF-REC-13, RNF-SEG-06, RNF-REN-02, RNF-MAN-05.
"""

import gzip
import json
import logging
import os
import time
from datetime import date

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core import backup
from apps.core.logging import JsonFormatter
from apps.guests.models import Guest
from apps.reservations.models import Reservation

OLD = timezone.make_aware(timezone.datetime(2018, 1, 1))


def test_pwa_manifest_service_worker_and_offline_page(client):
    m = client.get("/manifest.webmanifest").json()
    assert m["display"] == "standalone" and any(i["sizes"] == "512x512" for i in m["icons"])
    sw = client.get("/sw.js")
    assert sw["Service-Worker-Allowed"] == "/" and b"caches.open" in sw.content
    assert b"/reportes/arrivals/" in sw.content  # contingencia guardada para usar sin internet
    assert client.get("/sin-conexion/").status_code == 200  # sin iniciar sesión


def test_backup_is_compressed_verified_and_rotated(setup, book, settings, tmp_path):
    settings.BACKUP_DIR = str(tmp_path)
    book()
    path = backup.create_backup()
    assert path.exists() and backup.verify(path) > 10
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        models = {row["model"] for row in json.load(fh)}
    assert "reservations.reservation" in models and "sessions.session" not in models
    old = tmp_path / "pms-20200101-000000.json.gz"
    old.write_bytes(path.read_bytes())
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    assert backup.purge_old() == 1 and not old.exists()
    call_command("backup_pms", "--verify")


def test_guest_data_expires_after_retention_rnf_seg_06(setup, book, settings):
    settings.GUEST_RETENTION_YEARS = 5
    stale = Guest.objects.create(first_name="Viejo", last_name="Cliente", email="viejo@example.com")
    Guest.objects.filter(pk=stale.pk).update(created_at=OLD)
    book()  # María tiene estadía reciente: se conserva
    Guest.objects.filter(pk=setup.peruvian.pk).update(created_at=OLD)
    assert backup.expire_guest_data(today=date(2026, 7, 10)) == 1
    stale.refresh_from_db()
    setup.peruvian.refresh_from_db()
    assert stale.first_name == "Anonimizado" and stale.email == ""
    assert setup.peruvian.first_name == "María"


def test_history_does_not_slow_reservation_search_rnf_ren_02(setup, login):
    client = login(setup.admin)
    url = reverse("reservations:reservation_list") + "?q=Quispe"
    with CaptureQueriesContext(connection) as before:
        client.get(url)
    call_command("generate_history", "--count", "3000", "--guests", "50", stdout=open(os.devnull, "w"))
    assert Reservation.objects.filter(code__startswith="H").count() == 3000
    t0 = time.perf_counter()
    with CaptureQueriesContext(connection) as after:
        resp = client.get(url)
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200
    assert len(after) <= len(before) + 1  # sin consultas N+1 al crecer el historial
    assert elapsed < 1.0  # RNF-REN-01: búsqueda en menos de 1 s


def test_json_log_lines_have_request_context():
    record = logging.LogRecord("apps.test", logging.WARNING, __file__, 1, "Hola %s", ("mundo",), None)
    record.pms_user, record.pms_property, record.pms_ip = "lucia", 3, "10.0.0.1"
    data = json.loads(JsonFormatter().format(record))
    assert data["msg"] == "Hola mundo" and data["user"] == "lucia" and data["level"] == "WARNING"


def test_manual_renders_every_chapter_and_help_button_rnf_man_03(admin_user, login):
    from apps.core.help import TOPICS, markdown_to_html, topic_for_path

    client = login(admin_user)
    assert client.get("/ayuda/").status_code == 200
    for slug in TOPICS:
        resp = client.get(f"/ayuda/{slug}/")
        assert resp.status_code == 200, slug
        assert b"<h2>" in resp.content, slug
    assert topic_for_path("/recepcion/check-in/5/") == "recepcion"
    assert topic_for_path("/tours/") == "ventas"
    assert b'href="/ayuda/inicio/"' in client.get("/").content
    # el conversor escapa HTML: un capítulo no puede inyectar código
    html = markdown_to_html("Hola <script>alert(1)</script> [x](javascript:alert(1)) **ok**")
    assert "<script>" not in html and "javascript:" not in html and "<strong>ok</strong>" in html
