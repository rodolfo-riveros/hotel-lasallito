from datetime import time

import pytest

from apps.accounts.models import PropertyAccess, Role, User
from apps.accounts.services import seed_default_roles
from apps.core.models import Property

TEST_PASSWORD = "clave-de-prueba-123"


@pytest.fixture
def roles(db):
    return {r.code: r for r in seed_default_roles()}


@pytest.fixture
def hotel(db):
    return Property.objects.create(
        code="hotel-prueba",
        name="Hotel de Prueba",
        legal_name="Hotel de Prueba S.A.C.",
        ruc="20600000001",
        check_in_time=time(14),
        check_out_time=time(11),
    )


@pytest.fixture
def other_hotel(db):
    return Property.objects.create(
        code="otro-hotel", name="Otro Hotel", legal_name="Otro Hotel S.A.C.", ruc="20600000002"
    )


@pytest.fixture
def make_user(db, hotel, roles):
    """Crea un usuario con el rol indicado en `hotel` (o sin acceso si role=None)."""

    def _make(username="usuario", role="receptionist", property_obj=None, **extra):
        user = User.objects.create_user(username=username, password=TEST_PASSWORD, **extra)
        if role:
            PropertyAccess.objects.create(user=user, property=property_obj or hotel, role=roles[role])
        return user

    return _make


@pytest.fixture
def login(client):
    def _login(user):
        client.force_login(user)
        return client

    return _login


@pytest.fixture
def admin_user(make_user):
    return make_user("admin", role="admin")


@pytest.fixture
def receptionist(make_user):
    return make_user("recepcion", role="receptionist")


__all__ = ["Role", "TEST_PASSWORD"]
