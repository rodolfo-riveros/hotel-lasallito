"""RNF-REN-01: con la base en la nube cada consulta cuesta ~150 ms, así que las pantallas
de recepción deben usar pocas consultas. Esta prueba fija un presupuesto por pantalla."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

pytestmark = pytest.mark.django_db

BUDGET = {
    "core:dashboard": 10,
    "frontdesk:panel": 8,
    "reservations:tape_chart": 12,
    "rooms:rack": 6,
    "folio:folio_list": 4,
    "housekeeping:board": 10,
    "reservations:reservation_list": 5,
    "guests:guest_list": 5,
}


LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "budget"}}


@pytest.fixture
def real_cache(settings):
    from django.core.cache import cache

    settings.CACHES = LOCMEM
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
    cache.clear()
    yield
    cache.clear()


def test_query_budget(real_cache, hotel, roles, make_user, client):
    from apps.core.demo import load_bookings, load_operations

    admin = make_user("admin", role="admin")
    _t, _r, guests = load_operations(hotel)
    load_bookings(hotel, admin, guests)
    client.force_login(admin)
    client.get("/")
    report = {}
    for name in BUDGET:
        with CaptureQueriesContext(connection) as ctx:
            client.get(reverse(name))
        report[name] = len(ctx.captured_queries)
    print("QUERIES", report)
    over = {k: v for k, v in report.items() if v > BUDGET[k]}
    assert not over, f"Pantallas con demasiadas consultas: {over}"
