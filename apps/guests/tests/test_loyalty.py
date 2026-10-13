"""Programa de fidelidad: RF-HUE-04 (compartido entre hoteles, RF-MUL-03)."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.core.models import AuditLog
from apps.frontdesk import services as fd
from apps.guests import loyalty
from apps.guests.models import LoyaltyTier, LoyaltyTransaction


@pytest.fixture
def tiers(db):
    LoyaltyTier.objects.create(name="Andino", min_points=0)
    return LoyaltyTier.objects.create(name="Cóndor", min_points=50, earn_multiplier=Decimal("1.5"))


def _stay(setup, book, room_index=0):
    r = book(room=setup.rooms[room_index])
    fd.check_in(r, user=setup.receptionist, charge_early=False, allow_dirty=True)
    return r


def test_points_on_checkout_and_tier_rf_hue_04(setup, book, tiers):
    r = _stay(setup, book)
    tx = loyalty.award_stay_points(r, Decimal("600"))
    assert tx.points == 60  # 1 punto por cada S/ 10
    assert loyalty.award_stay_points(r, Decimal("600")) is None  # una sola vez por estadía
    setup.peruvian.refresh_from_db()
    assert setup.peruvian.loyalty_points == 60
    assert loyalty.tier_for(setup.peruvian) == tiers
    r2 = _stay(setup, book, 1)
    assert loyalty.award_stay_points(r2, Decimal("100")).points == 15  # el nivel Cóndor multiplica × 1.5


def test_redeem_points_as_folio_payment_with_audit(setup, book, tiers):
    r = _stay(setup, book)
    loyalty.award_stay_points(r, Decimal("1000"))
    guest = setup.peruvian
    from apps.folio import services as folio

    folio.post_charge(r.main_folio, folio.get_concept(setup.hotel, "lodging"), Decimal("300"))
    payment = loyalty.redeem(guest, r.main_folio, 100, setup.receptionist)
    assert payment.method == "points" and payment.amount == Decimal("10.00")
    guest.refresh_from_db()
    assert guest.loyalty_points == 0
    assert LoyaltyTransaction.objects.filter(kind="redeem", points=-100).exists()
    assert AuditLog.objects.filter(action="discount", object_type="folio.Payment").exists()
    with pytest.raises(ValidationError):
        loyalty.redeem(guest, r.main_folio, 1, setup.receptionist)


def test_points_shared_across_properties_rf_mul_03(setup, book, other_hotel, tiers):
    r = _stay(setup, book)
    loyalty.award_stay_points(r, Decimal("500"))
    loyalty.adjust(setup.peruvian, other_hotel, 20, "Cortesía por reclamo", setup.admin)
    setup.peruvian.refresh_from_db()
    assert setup.peruvian.loyalty_points == 70
    assert set(setup.peruvian.loyalty_transactions.values_list("property__code", flat=True)) == {
        setup.hotel.code,
        other_hotel.code,
    }


def test_loyalty_page(setup, book, tiers, login):
    client = login(setup.manager)
    resp = client.get(reverse("guests:guest_loyalty", args=[setup.peruvian.pk]))
    assert resp.status_code == 200
    resp = client.post(
        reverse("guests:guest_loyalty", args=[setup.peruvian.pk]),
        {"action": "adjust", "points": "25", "reason": "Bienvenida"},
    )
    setup.peruvian.refresh_from_db()
    assert setup.peruvian.loyalty_points == 25
    assert client.get(reverse("guests:tier_list")).status_code == 200
