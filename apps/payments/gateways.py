"""Adaptadores de pasarela de pago (sección 9: Izipay, Niubiz o Culqi).

`PAYMENT_GATEWAY=test` usa `TestGateway`, que imita la página de pago alojada de
una pasarela real con las tarjetas de prueba publicadas por los proveedores.
Los adaptadores reales se completan cuando el hotel tenga cuenta (sección 11.2).
"""

from dataclasses import dataclass

from django.conf import settings
from django.urls import reverse


@dataclass
class ChargeResult:
    ok: bool
    reference: str = ""
    last4: str = ""
    brand: str = ""
    error: str = ""


class Gateway:
    code = "base"

    def checkout_url(self, payment) -> str:  # pragma: no cover - interfaz
        raise NotImplementedError


class TestGateway(Gateway):
    """Página de pago de prueba. Tarjetas: 4111 1111 1111 1111 (aprobada), 4000 0000 0000 0002 (rechazada)."""

    code = "test"
    APPROVED = {"4111111111111111": "Visa", "5111111111111118": "Mastercard", "4970100000000055": "Visa"}
    DECLINED = {"4000000000000002": "Fondos insuficientes", "4000000000000069": "Tarjeta vencida"}

    def checkout_url(self, payment) -> str:
        return reverse("payments:test_checkout", args=[payment.token])

    def charge(self, card_number: str) -> ChargeResult:
        number = "".join(c for c in card_number if c.isdigit())
        if number in self.DECLINED:
            return ChargeResult(False, error=self.DECLINED[number])
        if number in self.APPROVED:
            import uuid

            return ChargeResult(
                True,
                reference=f"TEST-{uuid.uuid4().hex[:10].upper()}",
                last4=number[-4:],
                brand=self.APPROVED[number],
            )
        return ChargeResult(False, error="Use una tarjeta de prueba de la pasarela")


class CulqiGateway(Gateway):
    """Culqi: el formulario Culqi Checkout tokeniza la tarjeta en el navegador."""

    code = "culqi"

    def checkout_url(self, payment):
        raise NotImplementedError("Configure CULQI_PUBLIC_KEY y CULQI_SECRET_KEY y complete este adaptador.")


GATEWAYS = {"test": TestGateway, "culqi": CulqiGateway}


def get_gateway() -> Gateway:
    return GATEWAYS.get(getattr(settings, "PAYMENT_GATEWAY", "test"), TestGateway)()
