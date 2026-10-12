"""Inicio de sesión, bloqueo e inactividad (RNF-SEG-01, RNF-SEG-03)."""

import time

import pytest
from django.urls import reverse

from apps.accounts.middleware import SESSION_ACTIVITY_KEY
from apps.core.models import AuditLog
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db


def test_passwords_use_argon2(settings):
    from django.conf import settings as dj

    from config.settings import base

    assert base.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")
    assert dj.AUTH_USER_MODEL == "accounts.User"


def test_login_success_is_audited(client, receptionist):
    response = client.post(reverse("accounts:login"), {"username": "recepcion", "password": TEST_PASSWORD})
    assert response.status_code == 302
    assert AuditLog.objects.filter(action=AuditLog.Action.LOGIN, username="recepcion").exists()


def test_failed_login_is_audited(client, receptionist):
    client.post(reverse("accounts:login"), {"username": "recepcion", "password": "incorrecta"})
    log = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
    assert log.changes == {"username": "recepcion"}


def test_account_locks_after_failed_attempts(client, receptionist, settings):
    for _ in range(settings.AXES_FAILURE_LIMIT):
        client.post(reverse("accounts:login"), {"username": "recepcion", "password": "incorrecta"})
    response = client.post(reverse("accounts:login"), {"username": "recepcion", "password": TEST_PASSWORD})
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_idle_session_is_closed(client, receptionist, settings):
    client.force_login(receptionist)
    session = client.session
    session[SESSION_ACTIVITY_KEY] = int(time.time()) - settings.SESSION_IDLE_SECONDS - 5
    session.save()
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]
    assert "_auth_user_id" not in client.session


def test_active_session_continues(client, receptionist):
    client.force_login(receptionist)
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_logout_requires_post(client, receptionist):
    client.force_login(receptionist)
    assert client.get(reverse("accounts:logout")).status_code == 405
    client.post(reverse("accounts:logout"))
    assert "_auth_user_id" not in client.session


def test_create_user_with_property_role(admin_user, login, hotel, roles):
    from apps.accounts.models import User

    client = login(admin_user)
    response = client.post(
        reverse("accounts:user_create"),
        {
            "username": "nuevo",
            "first_name": "Nuevo",
            "last_name": "Usuario",
            "password": "Machu-Picchu-2026",
            "preferred_language": "es",
            "is_active": "on",
            "access-TOTAL_FORMS": "1",
            "access-INITIAL_FORMS": "0",
            "access-MIN_NUM_FORMS": "0",
            "access-MAX_NUM_FORMS": "1000",
            "access-0-property": hotel.pk,
            "access-0-role": roles["housekeeping"].pk,
            "access-0-is_active": "on",
        },
    )
    assert response.status_code == 302, response.context["form"].errors
    user = User.objects.get(username="nuevo")
    assert user.check_password("Machu-Picchu-2026")
    assert user.role_for(hotel) == roles["housekeeping"]
    assert AuditLog.objects.filter(action=AuditLog.Action.PERMISSION, object_id=str(user.pk)).exists()
