from django.conf import settings


def pms(request):
    """Datos comunes para todas las plantillas: propiedad activa, menú y modo SUNAT."""
    from apps.accounts.menu import build_menu

    user = getattr(request, "user", None)
    current_property = getattr(request, "property", None)
    authenticated = user is not None and user.is_authenticated
    menu = build_menu(request) if authenticated else []
    role = None
    if authenticated and current_property is not None and not user.is_superuser:
        from apps.accounts.cache import permissions_for

        info = permissions_for(user, current_property.pk)[1]
        role = type("RoleInfo", (), info)() if info else None
    return {
        "current_property": current_property,
        "current_role": role,
        "unread_notifications": _unread(user, current_property) if authenticated else 0,
        "user_properties": getattr(request, "user_properties", []),
        "main_menu": menu,
        "sunat_simulated": settings.SUNAT_MODE == "simulator",
    }


def _unread(user, property_obj):
    try:
        from django.core.cache import cache

        from apps.comms.services import unread_count

        key = f"pms:unread:{user.pk}:{getattr(property_obj, 'pk', 0)}"
        value = cache.get(key)
        if value is None:
            value = unread_count(user, property_obj)
            cache.set(key, value, 30)
        return value
    except Exception:  # noqa: BLE001 - la campana nunca debe romper una página
        return 0
