"""Indicadores: RF-REP-01 (criterio de aceptación: ocupación, ADR y RevPAR frente a un cálculo manual)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.folio import services as folio
from apps.reports import services as rep
from apps.rooms.models import RoomBlock
from conftest import BUSINESS_DATE as D

pytestmark = pytest.mark.django_db


def test_kpis_match_manual_calculation(setup, book):
    # Pasado: 2 noches con cargos reales. 4 habitaciones, una bloqueada el primer día.
    start = D - timedelta(days=2)
    RoomBlock.objects.create(
        property=setup.hotel,
        room=setup.rooms[3],
        start_date=start,
        end_date=start + timedelta(days=1),
        reason="Pintura",
    )
    r = book(arrival_offset=-2, nights=2)
    r.status = "checked_out"
    r.save()
    lodging = folio.get_concept(setup.hotel, "lodging")
    for i in range(2):
        folio.post_charge(r.main_folio, lodging, Decimal("300"), service_date=start + timedelta(days=i))
    stats = rep.kpis(setup.hotel, start, D)
    # Manual: disponibles = 3 + 4 = 7; vendidas = 2; ingreso = 600
    assert stats["available"] == 7
    assert stats["sold"] == 2
    assert stats["revenue"] == Decimal("600")
    assert stats["occupancy"] == Decimal("28.6")
    assert stats["adr"] == Decimal("300.00")
    assert stats["revpar"] == Decimal("85.71")


def test_future_uses_booked_rates_for_forecast(setup, book):
    book(arrival_offset=1, nights=2)
    stats = rep.kpis(setup.hotel, D + timedelta(days=1), D + timedelta(days=3))
    assert stats["sold"] == 2 and stats["revenue"] == Decimal("600.00")
    assert rep.forecast(setup.hotel)[0]["days"] == 30


def test_guests_by_country_and_mincetur(setup, book):
    r1 = book(guest=setup.foreigner, arrival_offset=-3, nights=2)
    r2 = book(arrival_offset=-3, nights=1)
    for r in (r1, r2):
        r.status = "checked_out"
        r.save()
    rows = rep.mincetur_monthly(setup.hotel, D.year, D.month)
    assert rows["total_arrivals"] == 4
    assert rows["national_arrivals"] == 2 and rows["foreign_arrivals"] == 2
    assert rows["total_overnights"] == 2 * 2 + 1 * 2
    assert rows["rows"][0]["code"] == "PE"
