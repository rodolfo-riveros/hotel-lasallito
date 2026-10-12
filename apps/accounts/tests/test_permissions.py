"""Pruebas de permisos por rol y por propiedad (RF-SEG-01, RF-SEG-02, RNF-SEG-02)."""

import pytest
from django.urls import reverse

from apps.accounts.models import PropertyAccess
from apps.accounts.permissions import DEFAULT_ROLES, all_permission_codes

pytestmark = pytest.mark.django_db


class TestRoleCatalog:
    def test_default_roles_only_reference_existing_permissions(self):
        valid = set(all_permission_codes())
        for spec in DEFAULT_ROLES:
            assert set(spec["permissions"]) <= valid, spec["code"]

    def test_every_role_can_see_dashboard(self, roles):
        for role in roles.values():
            assert "dashboard.view" in role.permission_codes()

    def test_admin_does_not_operate_cash(self, roles):
        """Sección 3: el administrador configura todo pero no opera caja."""
        codes = roles["admin"].permission_codes()
        assert "folio.view" in codes
        assert "folio.create" not in codes
        assert "folio.edit" not in codes

    def test_receptionist_cannot_see_purchasing_or_inventory(self, roles):
        """Sección 3: recepción no ve costos de compra ni márgenes."""
        codes = roles["receptionist"].permission_codes()
        assert not any(c.startswith(("purchasing.", "inventory.")) for c in codes)

    def test_sales_does_not_charge(self, roles):
        codes = roles["sales"].permission_codes()
        assert "folio.create" not in codes

    def test_storekeeper_does_not_issue_invoices(self, roles):
        codes = roles["storekeeper"].permission_codes()
        assert not any(c.startswith("billing.") for c in codes)

    def test_manager_approves(self, roles):
        codes = roles["manager"].permission_codes()
        assert {"folio.approve", "reservations.approve", "rates.edit"} <= codes

    def test_seed_does_not_overwrite_customized_roles(self, roles):
        from apps.accounts.services import seed_default_roles

        role = roles["receptionist"]
        role.permissions.clear()
        seed_default_roles()
        role.refresh_from_db()
        assert role.permissions.count() == 0


class TestPropertyScopedPermissions:
    def test_user_has_role_permissions_only_in_assigned_property(self, make_user, hotel, other_hotel):
        user = make_user("lucia", role="receptionist")
        assert user.has_pms_perm(hotel, "reservations.create")
        assert not user.has_pms_perm(other_hotel, "reservations.create")

    def test_different_roles_per_property(self, make_user, roles, hotel, other_hotel):
        user = make_user("jorge", role="receptionist")
        PropertyAccess.objects.create(user=user, property=other_hotel, role=roles["manager"])
        assert not user.has_pms_perm(hotel, "reservations.approve")
        assert user.has_pms_perm(other_hotel, "reservations.approve")

    def test_inactive_access_grants_nothing(self, make_user, hotel):
        user = make_user("ines", role="receptionist")
        user.property_accesses.update(is_active=False)
        user = type(user).objects.get(pk=user.pk)
        assert user.pms_permissions(hotel) == frozenset()

    def test_inactive_user_has_no_permissions(self, make_user, hotel):
        user = make_user("baja", role="manager", is_active=False)
        assert not user.has_pms_perm(hotel, "dashboard.view")

    def test_superuser_has_everything(self, db, hotel):
        from apps.accounts.models import User

        root = User.objects.create_superuser("root", password="x-very-long-password")
        assert root.has_pms_perm(hotel, "settings.edit")
        assert root.has_pms_perm(None, "audit.view")


# Vistas protegidas: (url, permiso requerido). Cada una se prueba contra un rol
# que lo tiene y otro que no (RNF-SEG-02: pruebas automáticas de permisos).
PROTECTED_VIEWS = [
    ("accounts:user_list", "accounts.view"),
    ("accounts:user_create", "accounts.create"),
    ("accounts:role_list", "accounts.view"),
    ("core:property_settings", "settings.view"),
    ("core:exchange_rates", "settings.view"),
    ("core:tax_list", "settings.view"),
    ("core:tax_create", "settings.edit"),
    ("core:audit_list", "audit.view"),
]


@pytest.mark.parametrize(("url_name", "perm"), PROTECTED_VIEWS)
def test_views_enforce_permissions(url_name, perm, make_user, login, roles):
    url = reverse(url_name)
    allowed_role = next(code for code, r in roles.items() if perm in r.permission_codes())
    denied_role = next(code for code, r in roles.items() if perm not in r.permission_codes())

    allowed = login(make_user(f"si-{allowed_role}", role=allowed_role))
    assert allowed.get(url).status_code == 200
    allowed.logout()

    denied = login(make_user(f"no-{denied_role}", role=denied_role))
    assert denied.get(url).status_code == 403


def test_anonymous_is_redirected_to_login(client):
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_user_without_property_access_is_denied(make_user, login):
    client = login(make_user("sin-acceso", role=None))
    assert client.get(reverse("core:dashboard")).status_code == 403


@pytest.mark.parametrize(
    ("role", "visible", "hidden"),
    [
        ("housekeeping", ["housekeeping", "rooms"], ["folio", "accounts", "inventory"]),
        ("receptionist", ["frontdesk", "reservations", "folio"], ["purchasing", "inventory", "accounts"]),
        ("admin", ["accounts", "settings", "audit"], []),
    ],
)
def test_menu_shows_only_permitted_modules(role, visible, hidden, make_user, login):
    client = login(make_user(f"menu-{role}", role=role))
    response = client.get(reverse("core:dashboard"))
    codes = {item["code"] for section in response.context["main_menu"] for item in section["items"]}
    assert set(visible) <= codes
    assert not (set(hidden) & codes)


def test_role_matrix_update_is_audited(admin_user, login, roles):
    from apps.core.models import AuditLog

    client = login(admin_user)
    role = roles["housekeeping"]
    current = sorted(role.permission_codes())
    response = client.post(
        reverse("accounts:role_edit", args=[role.pk]),
        {
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "max_discount_percent": "0",
            "approval_limit": "0",
            "perm": current + ["maintenance.edit"],
        },
    )
    assert response.status_code == 302
    role.refresh_from_db()
    assert "maintenance.edit" in role.permission_codes()
    log = AuditLog.objects.filter(action=AuditLog.Action.PERMISSION).latest("timestamp")
    assert log.changes["agregados"] == ["maintenance.edit"]
    assert log.username == "admin"


def test_switch_property_only_to_accessible(make_user, login, hotel, other_hotel):
    client = login(make_user("cambio", role="receptionist"))
    client.post(reverse("accounts:switch_property"), {"property": other_hotel.pk})
    response = client.get(reverse("core:dashboard"))
    assert response.context["current_property"] == hotel
