"""Núcleo: auditoría inmutable, borrado lógico, tipo de cambio e impuestos."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.urls import reverse

from apps.core import audit
from apps.core.models import AuditLog, Currency, ExchangeRate, Property, TaxRule
from apps.core.request_context import RequestInfo, reset_request_info, set_request_info
from apps.core.templatetags.pms import money

pytestmark = pytest.mark.django_db


class TestAuditLog:
    """RNF-SEG-03: auditoría inmutable de acciones críticas."""

    def test_log_records_user_ip_and_changes(self, receptionist, hotel):
        token = set_request_info(RequestInfo(user=receptionist, ip_address="10.0.0.7", user_agent="pytest"))
        try:
            log = audit.log(AuditLog.Action.DISCOUNT, hotel, changes={"descuento": [0, Decimal("10.50")]})
        finally:
            reset_request_info(token)
        assert log.username == "recepcion"
        assert log.ip_address == "10.0.0.7"
        assert log.property == hotel
        assert log.changes == {"descuento": [0, "10.50"]}

    def test_cannot_update_or_delete_instance(self, hotel):
        log = audit.log(AuditLog.Action.CREATE, hotel)
        log.reason = "manipulado"
        with pytest.raises(ValidationError):
            log.save()
        with pytest.raises(ValidationError):
            log.delete()

    def test_cannot_bulk_update_or_delete(self, hotel):
        audit.log(AuditLog.Action.CREATE, hotel)
        with pytest.raises(ValidationError):
            AuditLog.objects.all().update(reason="x")
        with pytest.raises(ValidationError):
            AuditLog.objects.all().delete()

    @pytest.mark.skipif(connection.vendor != "postgresql", reason="Trigger solo en PostgreSQL")
    def test_database_trigger_blocks_raw_update(self, hotel):
        audit.log(AuditLog.Action.CREATE, hotel)
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE core_auditlog SET reason = 'x'")

    def test_log_changes_only_records_differences(self, hotel):
        before = audit.snapshot(hotel, ["name", "phone"])
        hotel.phone = "+51 84 123456"
        hotel.save()
        log = audit.log_changes(hotel, before)
        assert log.changes == {"phone": ["", "+51 84 123456"]}
        assert audit.log_changes(hotel, audit.snapshot(hotel, ["name"])) is None


class TestSoftDelete:
    """RNF-INT-03: borrado lógico, nunca físico."""

    def test_delete_marks_and_hides(self, hotel, receptionist):
        token = set_request_info(RequestInfo(user=receptionist))
        try:
            hotel.delete()
        finally:
            reset_request_info(token)
        assert not Property.objects.filter(pk=hotel.pk).exists()
        stored = Property.all_objects.get(pk=hotel.pk)
        assert stored.is_deleted
        assert stored.deleted_by == receptionist

    def test_restore(self, hotel):
        hotel.delete()
        Property.all_objects.get(pk=hotel.pk).restore()
        assert Property.objects.filter(pk=hotel.pk).exists()

    def test_hard_delete_is_forbidden(self, hotel):
        with pytest.raises(ValidationError):
            hotel.hard_delete()


class TestTimestamps:
    def test_created_and_updated_by_are_set_from_request(self, receptionist, admin_user):
        token = set_request_info(RequestInfo(user=receptionist))
        try:
            prop = Property.objects.create(code="x", name="X", legal_name="X SAC", ruc="20600000003")
        finally:
            reset_request_info(token)
        token = set_request_info(RequestInfo(user=admin_user))
        try:
            prop.name = "Y"
            prop.save()
        finally:
            reset_request_info(token)
        prop.refresh_from_db()
        assert prop.created_by == receptionist
        assert prop.updated_by == admin_user


class TestExchangeRate:
    """RF-TAR-03: tipo de cambio diario editable."""

    def test_currencies_exist(self):
        assert set(Currency.objects.values_list("code", flat=True)) >= {"PEN", "USD"}

    def test_for_date_uses_latest_previous_rate(self):
        ExchangeRate.objects.create(date=date(2026, 10, 1), currency_id="USD", buy="3.70", sell="3.72")
        ExchangeRate.objects.create(date=date(2026, 10, 5), currency_id="USD", buy="3.75", sell="3.77")
        assert ExchangeRate.for_date("USD", date(2026, 10, 4)).sell == Decimal("3.7200")
        assert ExchangeRate.for_date("USD", date(2026, 10, 9)).sell == Decimal("3.7700")
        assert ExchangeRate.for_date("USD", date(2026, 9, 1)) is None

    def test_one_rate_per_day(self):
        ExchangeRate.objects.create(date=date(2026, 10, 1), currency_id="USD", buy="3.70", sell="3.72")
        with pytest.raises(IntegrityError), transaction.atomic():
            ExchangeRate.objects.create(date=date(2026, 10, 1), currency_id="USD", buy="3.71", sell="3.73")

    def test_sell_cannot_be_lower_than_buy(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            ExchangeRate.objects.create(date=date(2026, 10, 2), currency_id="USD", buy="3.80", sell="3.70")

    def test_correcting_rate_is_audited_as_rate_change(self, admin_user, login):
        client = login(admin_user)
        today = date.today()
        url = reverse("core:exchange_rates")
        client.post(url, {"date": today, "currency": "USD", "buy": "3.70", "sell": "3.72"})
        client.post(url, {"date": today, "currency": "USD", "buy": "3.71", "sell": "3.74"})
        assert ExchangeRate.objects.filter(date=today).count() == 1
        log = AuditLog.objects.get(action=AuditLog.Action.RATE_CHANGE)
        assert log.changes["sell"] == ["3.7200", "3.7400"]

    def test_receptionist_cannot_post_rate(self, receptionist, login):
        client = login(receptionist)
        response = client.post(
            reverse("core:exchange_rates"),
            {"date": date.today() - timedelta(days=1), "currency": "USD", "buy": "3.7", "sell": "3.8"},
        )
        assert response.status_code == 403


class TestTaxes:
    """RF-TAR-06: impuestos configurables con exoneración a no domiciliados."""

    def test_seed_creates_igv_18_exempt_for_non_domiciled(self):
        call_command("seed_pms", verbosity=0)
        hotel = Property.objects.get(code="la-sallito")
        igv = TaxRule.objects.get(property=hotel, code="igv")
        assert igv.rate == Decimal("18.00")
        assert igv.exempt_for_non_domiciled
        assert isinstance(igv.rate, Decimal)

    def test_tax_change_is_audited(self, admin_user, login, hotel):
        tax = TaxRule.objects.create(property=hotel, code="igv", name="IGV", rate=Decimal("18"))
        client = login(admin_user)
        response = client.post(
            reverse("core:tax_edit", args=[tax.pk]),
            {
                "code": "igv",
                "name": "IGV",
                "rate": "10.00",
                "applies_to": "all",
                "is_included_in_price": "on",
                "order": 1,
                "is_active": "on",
            },
        )
        assert response.status_code == 302
        log = AuditLog.objects.get(action=AuditLog.Action.RATE_CHANGE, object_id=str(tax.pk))
        assert log.changes["rate"] == ["18.00", "10.00"]

    def test_cannot_edit_tax_of_another_property(self, admin_user, login, other_hotel):
        tax = TaxRule.objects.create(property=other_hotel, code="igv", name="IGV", rate=Decimal("18"))
        client = login(admin_user)
        assert client.get(reverse("core:tax_edit", args=[tax.pk])).status_code == 404


class TestSeed:
    def test_seed_is_idempotent(self, monkeypatch):
        monkeypatch.setenv("DEMO_USER_PASSWORD", "practica-cusco-2026")
        call_command("seed_pms", "--demo", verbosity=0)
        call_command("seed_pms", "--demo", verbosity=0)
        from apps.accounts.models import Role, User

        assert Role.objects.count() == 11
        assert Property.objects.filter(code="la-sallito").count() == 1
        gerente = User.objects.get(username="gerente")
        assert gerente.role_for(Property.objects.get(code="la-sallito")).code == "manager"


def test_money_filter_formats_pen_and_usd():
    assert money(Decimal("1234.5")) == "S/&nbsp;1,234.50"
    assert money(Decimal("-10"), "USD") == "-US$&nbsp;10.00"
    assert money(None) == ""


def test_pages_render(admin_user, login):
    client = login(admin_user)
    for name in ["core:dashboard", "core:design_system", "core:offline", "accounts:role_create"]:
        assert client.get(reverse(name)).status_code == 200, name
