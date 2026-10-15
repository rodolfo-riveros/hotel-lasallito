# Reservas y grupos

Pantalla: **Reservas** (`g` `r`).

## Crear una reserva

1. Pulse **Nueva reserva** (`n`).
2. Busque al huésped por nombre, documento, correo o teléfono; si no existe, créelo ahí mismo.
3. Elija fechas, tipo de habitación, ocupación y plan de tarifa. El sistema muestra la disponibilidad y el precio noche por noche con temporadas, restricciones y promociones.
4. Opcional: habitación específica, preferencias, hora de llegada, pedidos especiales, depósito requerido.
5. Guarde. Se crea el folio y se envía la confirmación por correo/WhatsApp con el enlace al **portal del huésped**.

> Los descuentos manuales tienen un tope según su rol. Si lo supera, un supervisor debe aprobarlo. Todo descuento queda en la auditoría.

## Estados

| Estado | Significado |
| --- | --- |
| Cotización | Precio enviado, no bloquea inventario |
| Pendiente | Espera pago o garantía (por ejemplo, reserva web con pago en línea) |
| Confirmada / Garantizada | Bloquea inventario; garantizada tiene tarjeta o depósito |
| Lista de espera | Sin disponibilidad; se confirma si se libera |
| Check-in / Check-out | En casa / ya salió |
| No show / Cancelada | Con la penalidad de su política |

## Tape chart

**Reservas → Tape chart** muestra las habitaciones por día. Arrastre una reserva para moverla de habitación o de fechas; el sistema no permite superposiciones.

## Cancelar y no show

En la reserva, **Cancelar** con motivo. La penalidad se calcula según la política del plan (puede condonarse con permiso). El no show se marca en el cierre de día o a mano.

## Sobreventa (overbooking)

Solo un supervisor puede aceptar una reserva sin disponibilidad, dentro del límite configurado del hotel. El gerente recibe un aviso. Resuélvala asignando otra habitación (upgrade) o reubicando al huésped.

## Grupos

**Reservas → Grupos**: cree el bloque con fechas, tarifa pactada, cupos por tipo y fecha de liberación. Las reservas del grupo usan su cupo; lo no vendido se libera solo en la fecha indicada.

## Reservas que llegan solas

- **Web propia** (`/reservar/`): entran con canal "Web propia".
- **Booking, Expedia, Airbnb y agencias:** entran por el channel manager con su código externo y la tarifa que cobró el canal (ver [Tarifas, canales, web y tours](07-ventas.md)).
