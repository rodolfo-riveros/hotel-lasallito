"""Catálogo de módulos y acciones del PMS (RF-SEG-01).

Un permiso es "módulo.acción", por ejemplo "reservations.create". Los módulos
se declaran aquí una sola vez; el menú, la matriz de roles y las vistas lo leen
de este catálogo.
"""

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _


class Action:
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    VOID = "void"
    APPROVE = "approve"
    EXPORT = "export"


ACTIONS = [
    (Action.VIEW, _("Ver")),
    (Action.CREATE, _("Crear")),
    (Action.EDIT, _("Editar")),
    (Action.VOID, _("Anular")),
    (Action.APPROVE, _("Aprobar")),
    (Action.EXPORT, _("Exportar")),
]
ACTION_CODES = [code for code, _label in ACTIONS]


@dataclass(frozen=True)
class Module:
    code: str
    label: str
    icon: str
    section: str
    phase: int
    url_name: str | None = None  # None = aún no implementado
    actions: list[str] = field(default_factory=lambda: list(ACTION_CODES))


SECTION_OPERATION = _("Operación")
SECTION_SALES = _("Ventas")
SECTION_BACK = _("Administración")
SECTION_SYSTEM = _("Sistema")

MODULES: list[Module] = [
    Module("dashboard", _("Tablero"), "chart", SECTION_OPERATION, 0, "core:dashboard", [Action.VIEW]),
    Module("frontdesk", _("Recepción"), "key", SECTION_OPERATION, 1, "frontdesk:panel"),
    Module("reservations", _("Reservas"), "calendar", SECTION_OPERATION, 1, "reservations:reservation_list"),
    Module("rooms", _("Habitaciones"), "bed", SECTION_OPERATION, 1, "rooms:rack"),
    Module("housekeeping", _("Housekeeping"), "sparkles", SECTION_OPERATION, 1, "housekeeping:board"),
    Module("guests", _("Huéspedes"), "users", SECTION_OPERATION, 1, "guests:guest_list"),
    Module("pos", _("Restaurante y bar"), "coffee", SECTION_OPERATION, 1, "pos:outlets"),
    Module("folio", _("Folios y caja"), "wallet", SECTION_OPERATION, 1, "folio:folio_list"),
    Module("maintenance", _("Mantenimiento"), "wrench", SECTION_OPERATION, 2, "maintenance:wo_list"),
    Module("rates", _("Tarifas"), "tag", SECTION_SALES, 1, "rates:calendar"),
    Module("tours", _("Tours y traslados"), "map", SECTION_SALES, 3, "tours:agenda"),
    Module("channels", _("Channel manager"), "share", SECTION_SALES, 3, "channels:panel"),
    Module("booking_engine", _("Motor de reservas"), "globe", SECTION_SALES, 3, "booking_engine:group_list"),
    Module("comms", _("Comunicaciones"), "chat", SECTION_SALES, 1, "comms:inbox"),
    Module("billing", _("Facturación SUNAT"), "receipt", SECTION_BACK, 1, "billing:invoice_list"),
    Module("inventory", _("Almacén"), "box", SECTION_BACK, 2, "inventory:stock"),
    Module("purchasing", _("Compras"), "cart", SECTION_BACK, 2, "purchasing:requisition_list"),
    Module("reports", _("Reportes"), "document", SECTION_BACK, 1, "reports:index"),
    Module("accounts", _("Usuarios y roles"), "shield-check", SECTION_SYSTEM, 0, "accounts:user_list"),
    Module("settings", _("Configuración"), "cog", SECTION_SYSTEM, 0, "core:property_settings"),
    Module("classroom", _("Modo aula"), "academic", SECTION_SYSTEM, 3, "classroom:panel"),
    Module(
        "audit", _("Auditoría"), "eye", SECTION_SYSTEM, 0, "core:audit_list", [Action.VIEW, Action.EXPORT]
    ),
]
MODULES_BY_CODE = {m.code: m for m in MODULES}


def all_permission_codes() -> list[str]:
    return [f"{m.code}.{a}" for m in MODULES for a in m.actions]


# --------------------------------------------------------------------------
# Roles predeterminados (sección 3). Se crean con `manage.py seed_pms` y luego
# son editables desde la pantalla de roles.
# --------------------------------------------------------------------------

V, C, E, X, A, EX = (
    Action.VIEW,
    Action.CREATE,
    Action.EDIT,
    Action.VOID,
    Action.APPROVE,
    Action.EXPORT,
)


def _perms(spec: dict[str, list[str]]) -> list[str]:
    result = []
    for module, actions in spec.items():
        allowed = MODULES_BY_CODE[module].actions
        result += [f"{module}.{a}" for a in actions if a in allowed]
    return result


def _everything(actions: list[str], exclude: tuple[str, ...] = ()) -> dict[str, list[str]]:
    return {m.code: actions for m in MODULES if m.code not in exclude}


FRONT_DESK_BASE = {
    "dashboard": [V],
    "frontdesk": [V, C, E],
    "reservations": [V, C, E],
    "rooms": [V],
    "housekeeping": [V],
    "guests": [V, C, E],
    "folio": [V, C, E],
    "billing": [V, C],
    "rates": [V],
    "pos": [V],
    "tours": [V, C],
    "comms": [V, C],
    "reports": [V],
}

DEFAULT_ROLES = [
    {
        "code": "admin",
        "name": _("Administrador del sistema"),
        "description": _("Configura propiedades, usuarios, impuestos y series SUNAT. No opera caja."),
        "permissions": _perms(
            {
                **_everything([V, C, E, X, A, EX], exclude=("folio", "pos")),
                "folio": [V, EX],
                "pos": [V, EX],
            }
        ),
        "max_discount_percent": 100,
    },
    {
        "code": "manager",
        "name": _("Gerente general"),
        "description": _("Reportes, tarifas, aprobaciones y auditoría. Aprueba descuentos y anulaciones."),
        "permissions": _perms(
            {
                **_everything([V, A, EX]),
                "rates": [V, C, E, A, EX],
                "accounts": [V],
                "settings": [V],
            }
        ),
        "max_discount_percent": 100,
    },
    {
        "code": "receptionist",
        "name": _("Recepcionista"),
        "description": _("Reservas, check-in/out, cobros y folio. No ve costos de compra ni márgenes."),
        "permissions": _perms(FRONT_DESK_BASE),
        "max_discount_percent": 5,
    },
    {
        "code": "night_auditor",
        "name": _("Jefe de recepción / Night auditor"),
        "description": _("Cierre de día, corrección de folios y reportes de turno."),
        "permissions": _perms(
            {
                **FRONT_DESK_BASE,
                "frontdesk": [V, C, E, A],
                "reservations": [V, C, E, X],
                "folio": [V, C, E, X, A],
                "billing": [V, C, X],
                "reports": [V, EX],
            }
        ),
        "max_discount_percent": 15,
    },
    {
        "code": "sales",
        "name": _("Reservas / Ventas"),
        "description": _("Cotizaciones, grupos, agencias y contratos. No cobra en caja."),
        "permissions": _perms(
            {
                "dashboard": [V],
                "reservations": [V, C, E, X, EX],
                "guests": [V, C, E, EX],
                "rooms": [V],
                "rates": [V],
                "tours": [V, C, E],
                "channels": [V, C, E],
                "booking_engine": [V, E],
                "comms": [V, C],
                "reports": [V, EX],
            }
        ),
        "max_discount_percent": 10,
    },
    {
        "code": "housekeeping",
        "name": _("Housekeeping"),
        "description": _("Estado de habitaciones, tareas de limpieza y objetos perdidos."),
        "permissions": _perms(
            {
                "housekeeping": [V, C, E],
                "rooms": [V],
                "maintenance": [V, C],
            }
        ),
    },
    {
        "code": "maintenance",
        "name": _("Mantenimiento"),
        "description": _("Órdenes de trabajo y bloqueo de habitaciones."),
        "permissions": _perms({"maintenance": [V, C, E], "rooms": [V], "inventory": [V]}),
    },
    {
        "code": "storekeeper",
        "name": _("Almacenero"),
        "description": _("Ingresos, salidas, inventarios y kardex. No emite comprobantes."),
        "permissions": _perms({"inventory": [V, C, E, EX], "purchasing": [V]}),
    },
    {
        "code": "purchasing",
        "name": _("Compras"),
        "description": _("Requisiciones, órdenes de compra y proveedores, con aprobación por monto."),
        "permissions": _perms({"purchasing": [V, C, E, A, EX], "inventory": [V]}),
        "approval_limit": 2000,
    },
    {
        "code": "pos",
        "name": _("Restaurante / Bar"),
        "description": _("Comandas, cuentas y cargo a habitación. Solo su punto de venta."),
        "permissions": _perms({"pos": [V, C, E], "guests": [V]}),
        "max_discount_percent": 5,
    },
    {
        "code": "accountant",
        "name": _("Contador / Finanzas"),
        "description": _("Comprobantes, cuentas por cobrar y pagar, exportaciones. Solo lectura operativa."),
        "permissions": _perms(
            {
                "dashboard": [V],
                "billing": [V, EX],
                "folio": [V, EX],
                "reports": [V, EX],
                "purchasing": [V, EX],
                "inventory": [V, EX],
                "audit": [V],
            }
        ),
    },
    {
        "code": "teacher",
        "name": _("Docente"),
        "description": _(
            "Ve todos los hoteles de práctica, lanza escenarios y eventos y restablece los datos."
        ),
        "permissions": _perms(
            {
                **_everything([V, C, E, X, A, EX], exclude=("accounts",)),
                "accounts": [V, C, E],
            }
        ),
        "max_discount_percent": 100,
    },
]

# Todo rol ve el tablero (su contenido se adapta a los permisos del usuario).
for _role in DEFAULT_ROLES:
    if "dashboard.view" not in _role["permissions"]:
        _role["permissions"].insert(0, "dashboard.view")
