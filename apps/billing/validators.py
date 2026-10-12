"""Validaciones tributarias peruanas (RF-FAC-05, RF-COM-04)."""

from decimal import Decimal

RUC_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def ruc_is_valid(ruc: str) -> bool:
    """RUC de 11 dígitos con prefijo válido y dígito verificador (módulo 11)."""
    if not ruc or len(ruc) != 11 or not ruc.isdigit() or ruc[:2] not in ("10", "15", "16", "17", "20"):
        return False
    total = sum(int(d) * w for d, w in zip(ruc[:10], RUC_WEIGHTS, strict=True))
    check = 11 - total % 11
    check = {10: 0, 11: 1}.get(check, check)
    return check == int(ruc[10])


def ruc_check_digit(first10: str) -> int:
    total = sum(int(d) * w for d, w in zip(first10, RUC_WEIGHTS, strict=True))
    check = 11 - total % 11
    return {10: 0, 11: 1}.get(check, check)


def dni_is_valid(dni: str) -> bool:
    return bool(dni) and len(dni) == 8 and dni.isdigit()


UNITS = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
TEENS = [
    "DIEZ",
    "ONCE",
    "DOCE",
    "TRECE",
    "CATORCE",
    "QUINCE",
    "DIECISÉIS",
    "DIECISIETE",
    "DIECIOCHO",
    "DIECINUEVE",
]
TENS = ["", "", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
HUNDREDS = [
    "",
    "CIENTO",
    "DOSCIENTOS",
    "TRESCIENTOS",
    "CUATROCIENTOS",
    "QUINIENTOS",
    "SEISCIENTOS",
    "SETECIENTOS",
    "OCHOCIENTOS",
    "NOVECIENTOS",
]


def _below_thousand(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    h, rest = divmod(n, 100)
    words = [HUNDREDS[h]] if h else []
    if rest:
        if rest < 10:
            words.append(UNITS[rest])
        elif rest < 20:
            words.append(TEENS[rest - 10])
        elif rest < 30:
            words.append("VEINTE" if rest == 20 else "VEINTI" + UNITS[rest - 20])
        else:
            t, u = divmod(rest, 10)
            words.append(TENS[t] + (f" Y {UNITS[u]}" if u else ""))
    return " ".join(words)


def integer_to_words(n: int) -> str:
    if n == 0:
        return "CERO"
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append("UN MILLÓN" if millions == 1 else f"{integer_to_words(millions)} MILLONES")
    if thousands:
        parts.append("MIL" if thousands == 1 else f"{_below_thousand(thousands)} MIL")
    if units:
        parts.append(_below_thousand(units))
    return " ".join(parts).replace("VEINTIUNO MIL", "VEINTIÚN MIL").replace("UNO MIL", "UN MIL")


def amount_in_words(amount: Decimal, currency: str = "PEN") -> str:
    """Leyenda 1000: 'SON: CIENTO VEINTE CON 50/100 SOLES'."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    integer = int(amount)
    cents = int((amount - integer) * 100)
    name = "DÓLARES AMERICANOS" if currency == "USD" else "SOLES"
    return f"SON: {integer_to_words(integer)} CON {cents:02d}/100 {name}"
