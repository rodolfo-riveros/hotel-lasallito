"""Colores, íconos y textos de estado definidos UNA sola vez (RNF-UX-04).

Cada estado combina color + ícono + texto, de modo que se distingue sin
depender del color (apto para daltonismo). Las plantillas lo usan con
`{% status_badge "room" "dirty" %}`. Las clases `status-*` están en
static/src/input.css y los colores en tailwind.config.js (paleta `state`).
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Status:
    label: str
    tone: str  # available | occupied | dirty | cleaning | inspected | blocked | pending | confirmed | neutral | danger
    icon: str  # nombre del ícono en templates/components/icon.html


ROOM = {
    "vacant_clean": Status(_("Libre y limpia"), "available", "check-circle"),
    "vacant_dirty": Status(_("Libre y sucia"), "dirty", "sparkles"),
    "occupied_clean": Status(_("Ocupada limpia"), "occupied", "user"),
    "occupied_dirty": Status(_("Ocupada sucia"), "dirty", "user"),
    "cleaning": Status(_("En limpieza"), "cleaning", "clock"),
    "inspected": Status(_("Inspeccionada"), "inspected", "shield-check"),
    "out_of_service": Status(_("Fuera de servicio"), "blocked", "wrench"),
    "out_of_order": Status(_("Bloqueada"), "blocked", "lock"),
}

RESERVATION = {
    "quote": Status(_("Cotización"), "neutral", "document"),
    "pending": Status(_("Pendiente"), "pending", "clock"),
    "confirmed": Status(_("Confirmada"), "confirmed", "check-circle"),
    "guaranteed": Status(_("Garantizada"), "confirmed", "shield-check"),
    "checked_in": Status(_("Check-in"), "occupied", "key"),
    "checked_out": Status(_("Check-out"), "neutral", "arrow-right"),
    "no_show": Status(_("No show"), "danger", "x-circle"),
    "cancelled": Status(_("Cancelada"), "danger", "x-circle"),
}

GENERIC = {
    "active": Status(_("Activo"), "available", "check-circle"),
    "inactive": Status(_("Inactivo"), "neutral", "minus-circle"),
    "locked": Status(_("Bloqueado"), "blocked", "lock"),
}

GROUPS = {"room": ROOM, "reservation": RESERVATION, "generic": GENERIC}


def get_status(group: str, key: str) -> Status:
    return GROUPS.get(group, {}).get(key, Status(str(key), "neutral", "info"))
