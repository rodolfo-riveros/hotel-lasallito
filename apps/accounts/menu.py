"""Menú lateral filtrado por los permisos del usuario en la propiedad activa."""

from django.urls import NoReverseMatch, reverse

from .permissions import MODULES

# Atajo "g + letra" para ir a cada módulo (RNF-UX-03).
HOTKEYS = {
    "dashboard": "d",
    "frontdesk": "f",
    "reservations": "r",
    "rooms": "h",
    "housekeeping": "l",
    "guests": "e",
    "pos": "p",
    "folio": "c",
    "billing": "b",
    "reports": "i",
    "accounts": "u",
    "settings": "s",
    "audit": "a",
}

# Prefijo de URL que marca como activo el ítem (para módulos con varias pantallas).
ACTIVE_PREFIX = {
    "settings": "/configuracion/",
    "accounts": "/cuenta/",
}


def build_menu(request) -> list[dict]:
    user = request.user
    perms = user.pms_permissions(getattr(request, "property", None))
    path = request.path
    sections: dict[str, dict] = {}
    for module in MODULES:
        if f"{module.code}.view" not in perms:
            continue
        url = None
        if module.url_name:
            try:
                url = reverse(module.url_name)
            except NoReverseMatch:
                url = None
        section = sections.setdefault(str(module.section), {"label": module.section, "items": []})
        section["items"].append(
            {
                "code": module.code,
                "label": module.label,
                "icon": module.icon,
                "url": url,
                "phase": module.phase,
                "hotkey": HOTKEYS.get(module.code, ""),
                "active": bool(url)
                and (path == url if url == "/" else path.startswith(ACTIVE_PREFIX.get(module.code, url))),
            }
        )
    return list(sections.values())
