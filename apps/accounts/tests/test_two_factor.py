"""Doble factor con app autenticadora: RF-SEG-03."""

import time

import pyotp
import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts import two_factor
from apps.core.models import AuditLog
from conftest import TEST_PASSWORD


@pytest.fixture
def manager(make_user):
    return make_user("gerente2fa", role="manager")


def _enable(user):
    secret = two_factor.new_secret()
    two_factor.enable(user, secret, pyotp.TOTP(secret).now())
    user.refresh_from_db()
    return secret


def test_enable_requires_valid_code_and_is_audited_rf_seg_03(manager):
    secret = two_factor.new_secret()
    with pytest.raises(ValidationError):
        two_factor.enable(manager, secret, "000000")
    two_factor.enable(manager, secret, pyotp.TOTP(secret).now())
    manager.refresh_from_db()
    assert manager.totp_enabled and manager.totp_secret == secret
    assert AuditLog.objects.filter(action="permission", object_id=str(manager.pk)).exists()


def test_code_cannot_be_reused(manager):
    secret = _enable(manager)
    later = time.time() + 30
    code = pyotp.TOTP(secret).at(later)
    assert two_factor.verify(manager, code, at=later)
    assert not two_factor.verify(manager, code, at=later)  # repetición bloqueada


def test_login_asks_for_second_factor(manager, client):
    secret = _enable(manager)
    resp = client.post(reverse("accounts:login"), {"username": "gerente2fa", "password": TEST_PASSWORD})
    assert resp["Location"] == reverse("accounts:two_factor_verify")
    assert "_auth_user_id" not in client.session  # aún no ingresa
    assert client.post(reverse("accounts:two_factor_verify"), {"code": "123456"}).status_code == 200
    resp = client.post(
        reverse("accounts:two_factor_verify"), {"code": pyotp.TOTP(secret).at(time.time() + 30)}
    )
    assert resp.status_code == 302 and client.session["_auth_user_id"] == str(manager.pk)


def test_too_many_wrong_codes_restart_login(manager, client):
    _enable(manager)
    client.post(reverse("accounts:login"), {"username": "gerente2fa", "password": TEST_PASSWORD})
    for _ in range(5):
        resp = client.post(reverse("accounts:two_factor_verify"), {"code": "000000"})
    assert resp["Location"] == reverse("accounts:login")
    assert AuditLog.objects.filter(action="login_failed").count() >= 5


def test_setup_page_and_admin_reset(manager, admin_user, login, settings):
    client = login(manager)
    resp = client.get(reverse("accounts:two_factor_setup"))
    assert resp.status_code == 200 and b"<svg" in resp.content
    secret = client.session["pms_2fa_secret"]
    client.post(reverse("accounts:two_factor_setup"), {"code": pyotp.TOTP(secret).now()})
    manager.refresh_from_db()
    assert manager.totp_enabled
    login(admin_user).post(reverse("accounts:two_factor_reset", args=[manager.pk]))
    manager.refresh_from_db()
    assert not manager.totp_enabled and manager.totp_secret == ""


def test_required_roles_redirect_to_setup(manager, client, settings):
    settings.TWO_FACTOR_REQUIRED_ROLES = ["manager"]
    resp = client.post(reverse("accounts:login"), {"username": "gerente2fa", "password": TEST_PASSWORD})
    assert resp["Location"] == reverse("accounts:two_factor_setup")
