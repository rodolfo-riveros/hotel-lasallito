"""Genera las notas de requerimientos de la bóveda (docs/vault/01-Requerimientos).

Uso:  python scripts/vault_requirements.py
Lee el documento fuente guardado en la bóveda y marca como hechos los códigos de
DONE y como parciales los de PARTIAL. Actualice estos diccionarios al cerrar cada fase.
"""

import re
from pathlib import Path

vault = Path(__file__).resolve().parent.parent / "docs" / "vault"
src = vault / "01-Requerimientos" / "Documento de requerimientos.md"
text = src.read_text(encoding="utf-8")
if text.startswith("---"):
    text = text.split("---", 2)[2].lstrip()

F0, F1, F2, F3 = "fase 0", "fase 1", "fase 2", "fase 3"
DONE = {
    # Fase 0
    "RF-SEG-01": F0,
    "RF-SEG-02": F0,
    "RNF-SEG-02": F0,
    "RNF-SEG-03": F0,
    "RNF-SEG-07": F0,
    "RNF-INT-03": F0,
    "RF-BD-01": F0,
    "RF-BD-02": F0,
    "RF-BD-03": F0,
    "RF-BD-04": F0,
    "RF-BD-05": F0,
    "RNF-UX-04": F0,
    "RNF-I18N-02": F0,
    "RNF-MAN-01": F0,
    "RF-OBS-01": F0,
    "RF-OBS-02": F0,
    "RF-OBS-03": F0,
    "RF-OBS-04": F0,
    "RF-OBS-05": F1,
    "RF-OBS-06": F0,
    # Fase 1: reservas
    **{f"RF-RES-{n:02d}": F1 for n in range(1, 12)},
    # Recepción
    **{f"RF-REC-{n:02d}": F1 for n in (1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 14)},
    # Habitaciones, housekeeping, tarifas
    **{f"RF-HAB-{n:02d}": F1 for n in range(1, 6)},
    **{f"RF-HK-{n:02d}": F1 for n in (1, 2, 3, 4, 6, 7, 8)},
    **{f"RF-TAR-{n:02d}": F1 for n in range(1, 9)},
    # Huéspedes, POS, facturación, caja, reportes, comunicaciones
    **{f"RF-HUE-{n:02d}": F1 for n in (1, 2, 3, 6, 7)},
    **{f"RF-POS-{n:02d}": F1 for n in (1, 2, 3, 4, 6, 7, 8)},
    **{f"RF-FAC-{n:02d}": F1 for n in (1, 2, 3, 4, 5, 7, 8, 10)},
    **{f"RF-CAJ-{n:02d}": F1 for n in range(1, 6)},
    **{f"RF-REP-{n:02d}": F1 for n in range(1, 6)},
    "RF-COMU-01": F1,
    "RF-COMU-04": F1,
    "RF-SIM-06": F1,
    "RF-SIM-07": F1,
    # No funcionales
    "RNF-SEG-04": F1,
    "RNF-SEG-05": F1,
    "RNF-INT-01": F1,
    "RNF-INT-02": F1,
    "RNF-DIS-03": F1,
    "RNF-DIS-04": F1,
    "RNF-UX-01": F1,
    "RNF-UX-02": F1,
    "RNF-UX-03": F1,
    "RNF-UX-05": F1,
    "RNF-I18N-03": F1,
    # Fase 2
    **{f"RF-ALM-{n:02d}": F2 for n in range(1, 11)},
    **{f"RF-COM-{n:02d}": F2 for n in range(1, 6)},
    **{f"RF-MAN-{n:02d}": F2 for n in range(1, 5)},
    **{f"RF-POR-{n:02d}": F2 for n in range(1, 4)},
    "RF-POS-05": F2,
    "RF-HK-05": F2,
    "RF-REC-05": F2,
    "RF-REC-10": F2,
    "RF-HUE-05": F2,
    "RF-COMU-02": F2,
    "RF-COMU-03": F2,
    "RF-WEB-03": F2,
    "RF-WEB-05": F2,
    "RNF-REN-04": F2,
    "RNF-I18N-01": F2,
    # Fase 3
    **{f"RF-CHA-{n:02d}": F3 for n in range(1, 5)},
    **{f"RF-TUR-{n:02d}": F3 for n in range(1, 6)},
    **{f"RF-SIM-{n:02d}": F3 for n in range(1, 6)},
    **{f"RF-MUL-{n:02d}": F3 for n in range(1, 4)},
    "RF-WEB-01": F3,
    "RF-WEB-02": F3,
    "RF-WEB-04": F3,
    "RF-WEB-06": F3,
    "RF-HUE-04": F3,
}
PARTIAL = {
    "RNF-UX-06": "portal con etiquetas, contraste y salto al contenido; falta auditoría WCAG formal (fase 4)",
    "RF-SEG-03": "pendiente: doble factor (TOTP)",
    "RNF-SEG-01": "Argon2, bloqueo, inactividad y HTTPS en prod; falta probar despliegue",
    "RF-REC-13": "cargos, no shows, control de caja y reporte listos; falta respaldo automático",
    "RF-FAC-06": "facturación por cargos seleccionados y con crédito; falta agrupar varios folios",
    "RF-REP-06": "exportación PDF/Excel/CSV lista; falta envío programado",
    "RNF-MAN-02": "183 pruebas de reglas de negocio; falta medir cobertura",
    "RNF-MAN-03": "migraciones, datos de ejemplo y README; falta manual de usuario",
    "RNF-MAN-04": "GitHub Actions y .venv reproducible; faltan entornos separados",
    "RNF-MAN-05": "logging + Sentry opcional",
    "RF-BD-06": "Supabase Storage configurable; falta crear el bucket",
    "RF-BD-07": "proyecto de desarrollo; falta proyecto de producción/aula",
}

MODULES = {
    "SEG": ("Seguridad y roles", 0),
    "RES": ("Reservas", 1),
    "REC": ("Recepcion", 1),
    "HAB": ("Habitaciones", 1),
    "HK": ("Housekeeping", 1),
    "TAR": ("Tarifas", 1),
    "HUE": ("Huespedes", 1),
    "POS": ("Restaurante y bar", 1),
    "ALM": ("Almacen", 2),
    "COM": ("Compras", 2),
    "MAN": ("Mantenimiento", 2),
    "FAC": ("Facturacion SUNAT", 1),
    "CAJ": ("Caja y pagos", 1),
    "REP": ("Reportes", 1),
    "CHA": ("Channel manager", 3),
    "WEB": ("Motor de reservas", 3),
    "TUR": ("Tours y traslados", 3),
    "MUL": ("Multi-propiedad", 3),
    "COMU": ("Comunicaciones", 2),
    "POR": ("Portal del huesped", 2),
    "SIM": ("Modo aula y simulacion", 1),
    "BD": ("Base de datos Supabase", 0),
    "OBS": ("Bitacora Obsidian", 0),
}
pattern = re.compile(r"^- \*\*(RN?F-([A-Z0-9]+)-\d+):\*\*\s*(.+)$", re.M)
groups = {}
for code, mod, desc in pattern.findall(text):
    key = mod if code.startswith("RF-") else "RNF"
    groups.setdefault(key, []).append((code, desc.strip()))

out = vault / "01-Requerimientos"
out.mkdir(parents=True, exist_ok=True)
index = []


def line(code, desc):
    if code in DONE:
        return f"- [x] **{code}** {desc} ✅ {DONE[code]}"
    if code in PARTIAL:
        return f"- [ ] **{code}** {desc} — 🟡 parcial: {PARTIAL[code]}"
    return f"- [ ] **{code}** {desc}"


for mod, items in groups.items():
    if mod == "RNF":
        continue
    title, phase = MODULES.get(mod, (mod, 1))
    done = sum(1 for c, _ in items if c in DONE)
    body = (
        [
            "---",
            f"fase: {phase}",
            f"estado: {'completo' if done == len(items) else 'en curso' if done else 'pendiente'}",
            "tags: [requerimientos, modulo]",
            "---",
            f"# {title}",
            "",
            f"Requerimientos `RF-{mod}` del [[Documento de requerimientos]]. Fase prevista: {phase}.",
            "",
        ]
        + [line(c, d) for c, d in items]
        + [""]
    )
    (out / f"{title}.md").write_text("\n".join(body), encoding="utf-8")
    index.append((phase, title, done, len(items)))

rnf = groups.get("RNF", [])
by_area = {}
for code, desc in rnf:
    by_area.setdefault(code.split("-")[1], []).append((code, desc))
names = {
    "REN": "Rendimiento",
    "DIS": "Disponibilidad",
    "SEG": "Seguridad",
    "UX": "Experiencia de usuario",
    "I18N": "Idiomas",
    "MAN": "Mantenibilidad",
    "INT": "Integridad de datos",
}
body = [
    "---",
    "fase: 0-4",
    "estado: en curso",
    "tags: [requerimientos, no-funcionales]",
    "---",
    "# Requerimientos no funcionales",
    "",
    "Fuente: [[Documento de requerimientos]] sección 7.",
    "",
]
for area, items in by_area.items():
    body += [f"## {names.get(area, area)}", ""] + [line(c, d) for c, d in items] + [""]
(out / "No funcionales.md").write_text("\n".join(body), encoding="utf-8")
index.append((0, "No funcionales", sum(1 for c, _ in rnf if c in DONE), len(rnf)))

(out / "Documento de requerimientos.md").write_text(
    "---\ntags: [requerimientos, fuente]\n---\n" + text, encoding="utf-8"
)

index.sort()
rows = "\n".join(f"| [[{t}]] | {p} | {d}/{n} |" for p, t, d, n in index)
(out / "_Indice de requerimientos.md").write_text(
    "---\ntags: [requerimientos, indice]\n---\n# Índice de requerimientos\n\n| Módulo | Fase | Hechos |\n| --- | --- | --- |\n"
    + rows
    + "\n",
    encoding="utf-8",
)
print(len(index), "notas;", sum(len(v) for v in groups.values()), "requerimientos")
