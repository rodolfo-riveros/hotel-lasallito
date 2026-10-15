from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

from apps.core.status import get_status

register = template.Library()

# Íconos de trazo (estilo Heroicons, licencia MIT), definidos una sola vez.
ICONS = {
    "chart": "M3 3v18h18M7 15l4-4 3 3 5-6",
    "key": "M15 7a2 2 0 1 1 0 .01M21 7a6 6 0 0 1-7.7 5.7L11 15H9v2H7v2H3v-3.6l6.3-6.3A6 6 0 1 1 21 7Z",
    "calendar": "M8 2v4M16 2v4M3 9h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z",
    "bed": "M3 18v-7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7M3 18h18M3 14h18M7 9V6h4v3",
    "sparkles": "M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3ZM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z",
    "users": "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8",
    "user": "M20 21v-1a5 5 0 0 0-5-5H9a5 5 0 0 0-5 5v1M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
    "coffee": "M4 8h12v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8ZM16 10h2a2 2 0 0 1 0 4h-2M8 2v3M12 2v3",
    "wallet": "M3 7a2 2 0 0 1 2-2h13v4M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2ZM16 14h.01",
    "wrench": "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6Z",
    "tag": "M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9-9-9ZM7.5 7.5h.01",
    "map": "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2ZM9 4v14M15 6v14",
    "share": "M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
    "globe": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20",
    "chat": "M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12Z",
    "receipt": "M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2V3ZM9 8h6M9 12h6M9 16h3",
    "box": "M21 8 12 3 3 8v8l9 5 9-5V8ZM3 8l9 5 9-5M12 13v8",
    "cart": "M3 3h2l2.4 12h11l2-8H6M9 20a1 1 0 1 0 0 .01M18 20a1 1 0 1 0 0 .01",
    "document": "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6ZM14 3v6h6M8 13h8M8 17h5",
    "shield-check": "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3ZM9 12l2 2 4-4",
    "cog": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z",
    "eye": "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12ZM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    "check-circle": "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM8 12l3 3 5-6",
    "x-circle": "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM15 9l-6 6M9 9l6 6",
    "minus-circle": "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM8 12h8",
    "clock": "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM12 6v6l4 2",
    "lock": "M5 11h14v10H5V11ZM8 11V7a4 4 0 1 1 8 0v4",
    "info": "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM12 16v-4M12 8h.01",
    "arrow-right": "M5 12h14M13 6l6 6-6 6",
    "menu": "M4 6h16M4 12h16M4 18h16",
    "x": "M6 6l12 12M18 6 6 18",
    "sun": "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
    "moon": "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",
    "logout": "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
    "plus": "M12 5v14M5 12h14",
    "search": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
    "download": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    "building": "M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M16 9h2a2 2 0 0 1 2 2v10M3 21h18M8 7h4M8 11h4M8 15h4",
    "mountain": "M3 20 9.5 8l4 7 2.5-4 5 9H3Z",
    "currency": "M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
    "percent": "M19 5 5 19M6.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM17.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
    "wifi-off": "M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M2 8.8a15 15 0 0 1 4.2-2.7M10.7 5.1A15 15 0 0 1 22 8.8M5 12.9a10 10 0 0 1 5.2-2.8M19 12.9a10 10 0 0 0-2-1.5M12 20h.01",
    "academic": "M12 4 2 9l10 5 10-5-10-5Zm-6 7.5V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-4.5M22 9v6",
}


@register.simple_tag
def icon(name, size="w-5 h-5", extra=""):
    path = ICONS.get(name, ICONS["info"])
    return format_html(
        '<svg class="{} {} shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{}"/></svg>',
        size,
        extra,
        path,
    )


@register.simple_tag
def status_badge(group, key):
    """Insignia de estado: color + ícono + texto (RNF-UX-04)."""
    status = get_status(group, key)
    return format_html(
        '<span class="status status-{}">{}<span>{}</span></span>',
        status.tone,
        icon(status.icon, "w-3.5 h-3.5"),
        status.label,
    )


@register.simple_tag(takes_context=True)
def can(context, perm):
    """`{% can "reservations.create" as puede %}` en la propiedad activa."""
    request = context.get("request")
    if request is None or not request.user.is_authenticated:
        return False
    return request.user.has_pms_perm(getattr(request, "property", None), perm)


@register.filter
def money(value, currency="PEN"):
    """Formatea montos Decimal: S/ 1,234.50 o US$ 1,234.50 (RNF-I18N-02)."""
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return value
    symbol = {"PEN": "S/", "USD": "US$"}.get(currency, currency)
    sign = "-" if amount < 0 else ""
    return format_html("{}{}&nbsp;{}", sign, symbol, f"{abs(amount):,.2f}")


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if hasattr(mapping, "get") else None


@register.filter
def cell(value):
    """Valor de celda para tablas genéricas."""
    import datetime

    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return format_html(
            '<span class="{}">{}</span>',
            "text-state-available" if value else "text-ink-400",
            "Sí" if value else "No",
        )
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, datetime.datetime):
        from django.utils import timezone

        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
    if isinstance(value, datetime.date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return value


@register.filter
def lang_field(obj, field):
    """Campo traducido: `obj|lang_field:"name"` usa name_en / name_pt según el idioma activo."""
    from django.utils.translation import get_language

    lang = (get_language() or "es")[:2]
    if lang in ("en", "pt"):
        value = getattr(obj, f"{field}_{lang}", "")
        if value:
            return value
    return getattr(obj, field, "")


@register.filter
def dictget(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def sub(a, b):
    try:
        return a - b
    except TypeError:
        return ""


@register.filter
def hk_key(room):
    """Clave de estado de limpieza de una habitación (sin ocupación)."""
    return {
        "clean": "vacant_clean",
        "dirty": "vacant_dirty",
        "cleaning": "cleaning",
        "inspected": "inspected",
    }.get(getattr(room, "hk_status", ""), "vacant_clean")


@register.filter
def mul(a, b):
    """Multiplica dos montos Decimal (dos decimales)."""
    try:
        return (Decimal(str(a)) * Decimal(str(b))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.simple_tag(takes_context=True)
def help_url(context):
    """Enlace al capítulo del manual de la pantalla actual (RNF-UX-07)."""
    from apps.core.help import topic_for_path

    request = context.get("request")
    return f"/ayuda/{topic_for_path(request.path if request else '/')}/"
