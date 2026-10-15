"""Adaptadores de cerraduras y central telefónica (sección 10, fase 4: "integraciones opcionales").

`DOOR_LOCK=test|none|salto|onity` y `PBX=test|none|asterisk`. Las implementaciones de prueba
funcionan sin hardware: la cerradura de prueba "graba" una referencia y la central de prueba
acepta registros de llamada (CDR) por un webhook protegido con `PBX_TOKEN`. Los adaptadores
reales se completan cuando el hotel tenga el equipo.
"""

import secrets
from dataclasses import dataclass

from django.conf import settings


@dataclass
class EncodeResult:
    ok: bool
    card_refs: list
    message: str = ""


class LockAdapter:
    code = "base"

    def encode(self, room, valid_from, valid_to, copies=1) -> EncodeResult:  # pragma: no cover - interfaz
        raise NotImplementedError

    def revoke(self, card) -> bool:  # pragma: no cover - interfaz
        raise NotImplementedError


class TestLock(LockAdapter):
    """Codificador simulado: devuelve referencias como las de un codificador real."""

    code = "test"

    def encode(self, room, valid_from, valid_to, copies=1):
        refs = [f"T{room.number}-{secrets.token_hex(3).upper()}" for _ in range(copies)]
        return EncodeResult(True, refs, f"{copies} tarjeta(s) grabada(s)")

    def revoke(self, card):
        return True


class SaltoLock(LockAdapter):
    code = "salto"

    def encode(self, room, valid_from, valid_to, copies=1):
        raise NotImplementedError("Configure el servidor SALTO Space (SHIP) para usar este adaptador.")

    revoke = encode


LOCKS = {"test": TestLock, "salto": SaltoLock}


def get_lock() -> LockAdapter | None:
    code = getattr(settings, "DOOR_LOCK", "test")
    return LOCKS[code]() if code in LOCKS else None


# -- Central telefónica ------------------------------------------------------


def classify(number: str) -> str:
    """Clasifica el número marcado según el plan de numeración del Perú."""
    digits = "".join(c for c in number if c.isdigit() or c == "+")
    if digits.startswith(("+", "00")) and not digits.startswith(("+51", "0051")):
        return "international"
    digits = digits.removeprefix("+51").removeprefix("0051")
    if len(digits) <= 4:
        return "internal"
    if len(digits) == 9 and digits.startswith("9"):
        return "mobile"
    if digits.startswith("0"):
        return "national"
    return "local"


def parse_cdr(payload: dict) -> dict:
    """Formato normalizado del CDR (Asterisk/FreePBX lo envían con estos campos)."""
    return {
        "external_id": str(payload["uniqueid"]),
        "extension": str(payload["src"]),
        "dialed": str(payload["dst"]),
        "started_at": payload["start"],
        "seconds": int(payload.get("billsec") or payload.get("duration") or 0),
    }


def pbx_enabled() -> bool:
    return getattr(settings, "PBX", "test") != "none"
