"""Caché de permisos y propiedades por usuario (RNF-REN-01).

Con la base de datos en la nube cada consulta cuesta ~150 ms. Los permisos se
leen en cada página, así que se guardan en la caché de Django y se invalidan
subiendo una "versión" global cuando cambia un rol, un acceso o un permiso.
"""

from django.core.cache import cache

TTL = 300
VERSION_KEY = "pms:perm_version"


def _version() -> int:
    return cache.get_or_set(VERSION_KEY, 1, None)


def bump_version() -> None:
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, 2, None)


def _key(*parts) -> str:
    return "pms:" + ":".join(str(p) for p in (*parts, _version()))


def properties_for(user) -> list:
    """Propiedades activas a las que el usuario tiene acceso (objetos Property)."""
    key = _key("props", user.pk, int(user.is_superuser))
    props = cache.get(key)
    if props is None:
        props = list(user.accessible_properties().select_related("base_currency"))
        cache.set(key, props, TTL)
    return props


def permissions_for(user, property_id) -> tuple[frozenset, dict | None]:
    """(permisos, {"code", "name"} del rol) del usuario en la propiedad."""
    key = _key("perms", user.pk, property_id)
    cached = cache.get(key)
    if cached is None:
        from .models import PropertyAccess

        access = (
            PropertyAccess.objects.select_related("role")
            .filter(user=user, property_id=property_id, is_active=True)
            .first()
        )
        if access is None:
            cached = (frozenset(), None)
        else:
            cached = (
                access.role.permission_codes(),
                {"code": access.role.code, "name": access.role.name, "pk": access.role.pk},
            )
        cache.set(key, cached, TTL)
    return cached
