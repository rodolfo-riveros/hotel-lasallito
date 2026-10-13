---
fecha: 2026-10-13
fase: 2
estado: aceptada
tags: [decision, pagos, seguridad]
---
# Decisión: pagos en línea con página de pasarela alojada

**Contexto.** RF-WEB-03 y RF-POR-01 piden pagar en línea. RNF-SEG-04 exige que los datos de tarjeta nunca se
guarden en el sistema. El proveedor (Izipay, Niubiz o Culqi) aún no está elegido (sección 11.2).

**Decisión.**
- App `payments` con `OnlinePayment` y adaptadores en `gateways.py`. `PAYMENT_GATEWAY=test` por defecto.
- `TestGateway` imita la **página de pago alojada** de la pasarela: la tarjeta se ingresa "en la pasarela" y
  el PMS solo recibe el resultado (referencia, marca y últimos 4 dígitos).
- Tarjetas de prueba: 4111 1111 1111 1111 (aprobada) y 4000 0000 0000 0002 (rechazada).
- Al aprobarse, el pago entra al folio como "Enlace de pago / web". Una reserva pendiente pasa a garantizada.
- `complete()` es idempotente: una segunda notificación de la pasarela no duplica el pago.

**Pendiente.** Completar `CulqiGateway` (u otro adaptador) cuando el hotel tenga cuenta del proveedor.
