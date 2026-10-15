"""Manual de usuario y ayuda contextual (RNF-MAN-03, RNF-UX-07).

El manual vive en `docs/manual/*.md` (se lee en GitHub, en Obsidian y dentro del sistema).
Cada pantalla muestra un botón "Ayuda" que abre el capítulo de su módulo. El conversor de
Markdown es mínimo a propósito (títulos, listas, negrita, código, enlaces y tablas): escapa
todo el HTML, así un capítulo nunca puede inyectar código en la página.
"""

import re
from functools import lru_cache
from html import escape
from pathlib import Path

from django.conf import settings

MANUAL_DIR = Path(settings.BASE_DIR) / "docs" / "manual"

# slug -> (título, archivo, módulos del catálogo de permisos que abren este capítulo)
TOPICS = {
    "inicio": ("Primeros pasos", "00-primeros-pasos.md", ("dashboard",)),
    "recepcion": ("Recepción", "01-recepcion.md", ("frontdesk",)),
    "reservas": ("Reservas y grupos", "02-reservas.md", ("reservations",)),
    "habitaciones": (
        "Habitaciones y housekeeping",
        "03-habitaciones-housekeeping.md",
        ("rooms", "housekeeping"),
    ),
    "caja": ("Folios, caja y facturación", "04-caja-facturacion.md", ("folio", "billing")),
    "restaurante": ("Restaurante y bar", "05-restaurante.md", ("pos",)),
    "huespedes": ("Huéspedes y fidelidad", "06-huespedes.md", ("guests",)),
    "ventas": (
        "Tarifas, canales, web y tours",
        "07-ventas.md",
        ("rates", "channels", "booking_engine", "tours", "comms"),
    ),
    "operacion": (
        "Almacén, compras y mantenimiento",
        "08-almacen-compras-mantenimiento.md",
        ("inventory", "purchasing", "maintenance"),
    ),
    "reportes": ("Reportes", "09-reportes.md", ("reports",)),
    "administracion": (
        "Administración y seguridad",
        "10-administracion.md",
        ("accounts", "settings", "audit"),
    ),
    "aula": ("Modo aula (docentes)", "11-modo-aula.md", ("classroom",)),
}
MODULE_TOPIC = {module: slug for slug, (_t, _f, modules) in TOPICS.items() for module in modules}

# Prefijo de URL -> módulo, para elegir el capítulo de la pantalla actual.
PATH_MODULE = [
    ("/recepcion/", "frontdesk"),
    ("/integraciones/", "frontdesk"),
    ("/reservas/", "reservations"),
    ("/habitaciones/", "rooms"),
    ("/housekeeping/", "housekeeping"),
    ("/folios/", "folio"),
    ("/facturacion/", "billing"),
    ("/restaurante/", "pos"),
    ("/huespedes/", "guests"),
    ("/tarifas/", "rates"),
    ("/canales/", "channels"),
    ("/motor-web/", "booking_engine"),
    ("/tours/", "tours"),
    ("/comunicaciones/", "comms"),
    ("/almacen/", "inventory"),
    ("/compras/", "purchasing"),
    ("/mantenimiento/", "maintenance"),
    ("/reportes/", "reports"),
    ("/cuenta/", "accounts"),
    ("/configuracion/", "settings"),
    ("/auditoria/", "audit"),
    ("/aula/", "classroom"),
]


def topic_for_path(path: str) -> str:
    for prefix, module in PATH_MODULE:
        if path.startswith(prefix):
            return MODULE_TOPIC.get(module, "inicio")
    return "inicio"


def _inline(text: str) -> str:
    text = escape(text, quote=True)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    def link(m):
        label, href = m.group(1), m.group(2)
        if not re.match(r"^(/|https://|#|[\w-]+\.md$)", href):
            return label
        if href.endswith(".md"):
            slug = next((s for s, (_t, f, _m) in TOPICS.items() if f == href), None)
            href = f"/ayuda/{slug}/" if slug else "#"
        return f'<a href="{href}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)


def markdown_to_html(md: str) -> str:
    """Conversor mínimo y seguro (el contenido se escapa antes de dar formato)."""
    out, para, list_tag, table = [], [], None, []

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def flush_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def flush_table():
        if table:
            rows = [r for r in table if not re.match(r"^\|?\s*:?-{2,}", r)]
            html = ["<table>"]
            for i, row in enumerate(rows):
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                tag = "th" if i == 0 else "td"
                html.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
            html.append("</table>")
            out.append("".join(html))
            table.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("---") and not out and not para:
            continue
        if line.startswith("|"):
            flush_para()
            flush_list()
            table.append(line)
            continue
        flush_table()
        heading = re.match(r"^(#{1,4})\s+(.*)", line)
        bullet = re.match(r"^\s*[-*]\s+(.*)", line)
        number = re.match(r"^\s*\d+\.\s+(.*)", line)
        if heading:
            flush_para()
            flush_list()
            level = min(4, max(2, len(heading.group(1))))  # el h1 lo pone la página
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif bullet or number:
            flush_para()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                flush_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{_inline((bullet or number).group(1))}</li>")
        elif not line.strip():
            flush_para()
            flush_list()
        elif line.startswith("> "):
            flush_para()
            flush_list()
            out.append(f'<p class="note">{_inline(line[2:])}</p>')
        else:
            flush_list()
            para.append(line.strip())
    flush_para()
    flush_list()
    flush_table()
    return "\n".join(out)


@lru_cache(maxsize=32)
def _render_file(path: str, mtime: float) -> str:
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # frontmatter de Obsidian
    text = re.sub(r"^#\s+.*\n", "", text, count=1)  # el título va en la página
    return markdown_to_html(text)


def render_topic(slug: str) -> str | None:
    if slug not in TOPICS:
        return None
    path = MANUAL_DIR / TOPICS[slug][1]
    if not path.exists():
        return None
    return _render_file(str(path), path.stat().st_mtime)
