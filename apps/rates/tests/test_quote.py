"""Motor de tarifas: RF-TAR-01, RF-TAR-02, RF-TAR-03, RF-TAR-05, RF-WEB-04."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.rates.models import DateRestriction, Promotion
from apps.rates.services import quote

pytestmark = pytest.mark.django_db
D = date(2026, 7, 10)


def test_base_price_per_night(setup):
    q = quote(setup.rack, setup.double, D, D + timedelta(days=2))
    assert q.ok
    assert [n.amount for n in q.nights] == [Decimal("300.00"), Decimal("300.00")]
    assert q.total == Decimal("600.00")


def test_season_overrides_base_price_rf_tar_02(setup):
    q = quote(setup.rack, setup.double, date(2026, 7, 19), date(2026, 7, 22))
    assert [n.amount for n in q.nights] == [Decimal("300.00"), Decimal("400.00"), Decimal("400.00")]
    assert q.nights[1].season == "Alta"


def test_extra_adult_and_child_rf_tar_05(setup):
    q = quote(setup.rack, setup.double, D, D + timedelta(days=1), adults=3, children=0)
    assert q.nights[0].amount == Decimal("380.00")
    q = quote(setup.rack, setup.double, D, D + timedelta(days=1), adults=2, children=1)
    assert q.nights[0].amount == Decimal("340.00")


def test_occupancy_above_capacity_is_rejected(setup):
    q = quote(setup.rack, setup.double, D, D + timedelta(days=1), adults=3, children=1)
    assert not q.ok


def test_derived_plan_applies_adjustment_rf_tar_01(setup):
    q = quote(setup.corporate, setup.double, D, D + timedelta(days=1))
    assert q.nights[0].amount == Decimal("270.00")


def test_min_nights_and_closed_to_arrival_rf_tar_02(setup):
    DateRestriction.objects.create(
        property=setup.hotel, date_from=D, date_to=D + timedelta(days=3), min_nights=3
    )
    assert not quote(setup.rack, setup.double, D, D + timedelta(days=2)).ok
    assert quote(setup.rack, setup.double, D, D + timedelta(days=3)).ok
    DateRestriction.objects.create(
        property=setup.hotel,
        date_from=D + timedelta(days=10),
        date_to=D + timedelta(days=10),
        closed_to_arrival=True,
    )
    assert not quote(setup.rack, setup.double, D + timedelta(days=10), D + timedelta(days=12)).ok


def test_stop_sell(setup):
    DateRestriction.objects.create(
        property=setup.hotel,
        date_from=D + timedelta(days=1),
        date_to=D + timedelta(days=1),
        stop_sell=True,
        reason="Inti Raymi",
    )
    q = quote(setup.rack, setup.double, D, D + timedelta(days=3))
    assert any("Inti Raymi" in e for e in q.errors)


def test_usd_conversion_with_daily_rate_rf_tar_03(setup):
    q = quote(setup.rack, setup.double, D, D + timedelta(days=1), currency="USD")
    assert q.currency == "USD"
    assert q.nights[0].amount == Decimal("80.00")  # 300 / 3.75


def test_rounding_configurable_rf_tar_03(setup):
    setup.hotel.price_rounding = "1"
    setup.hotel.save()
    setup.corporate.adjustment_percent = Decimal("-7.5")
    setup.corporate.save()
    q = quote(setup.corporate, setup.double, D, D + timedelta(days=1))
    assert q.nights[0].amount == Decimal("278")  # 277.50 → 278


def test_promo_code_rf_web_04(setup):
    Promotion.objects.create(
        property=setup.hotel,
        code="VALLE10",
        name="Valle",
        discount_percent=Decimal("10"),
        valid_from=date(2020, 1, 1),
        valid_to=date(2030, 1, 1),
    )
    q = quote(setup.rack, setup.double, D, D + timedelta(days=2), promo_code="valle10")
    assert q.promotion is not None
    assert q.total == Decimal("540.00")


def test_cancellation_penalty_rules_rf_res_06(setup):
    nightly = [Decimal("300"), Decimal("300")]
    policy = setup.flexible
    assert policy.cancellation_penalty(D, D - timedelta(days=5), nightly, Decimal("600")) == 0
    assert policy.cancellation_penalty(D, D - timedelta(days=1), nightly, Decimal("600")) == Decimal("300")
    nonref = setup.nonref.cancellation_policy
    assert nonref.cancellation_penalty(D, D - timedelta(days=30), nightly, Decimal("600")) == Decimal("600")
