from django.conf import settings


def pms(request):
    """Datos comunes para todas las plantillas: propiedad activa, menú y modo SUNAT."""
    from apps.accounts.menu import build_menu

    user = getattr(request, "user", None)
    current_property = getattr(request, "property", None)
    authenticated = user is not None and user.is_authenticated
    menu = build_menu(request) if authenticated else []
    role = user.role_for(current_property) if authenticated else None
    return {
        "current_property": current_property,
        "current_role": role,
        "user_properties": getattr(request, "user_properties", []),
        "main_menu": menu,
        "sunat_simulated": settings.SUNAT_MODE == "simulator",
    }
