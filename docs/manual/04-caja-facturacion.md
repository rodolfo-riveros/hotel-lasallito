# Folios, caja y facturación

## Folio

Cada reserva tiene un folio principal con sus **cargos** (alojamiento, restaurante, minibar, tours, llamadas, lavandería) y **pagos**.

- **Agregar cargo:** elija el concepto; el IGV (y el cargo por servicio, si aplica) se calcula solo. A los extranjeros no domiciliados con pasaporte se les exonera el IGV del alojamiento.
- **Anular cargo:** solo con permiso y motivo; queda en la auditoría.
- **Transferir:** mueva cargos a otro folio (por ejemplo, a la cuenta de la empresa).
- **Folios adicionales:** para separar lo que paga la empresa de los extras del huésped.

## Cobros

Medios: efectivo en soles o dólares, tarjeta (POS), transferencia, Yape, Plin, enlace de pago, cuenta corriente (empresas con crédito) y **canje de puntos** de fidelidad.

> El efectivo exige tener la **caja abierta**. Los dólares se convierten con el tipo de cambio de compra del día.

## Caja

1. **Abrir caja** al iniciar el turno, con el fondo inicial.
2. Durante el turno, todos sus cobros en efectivo se suman a su caja.
3. **Cerrar caja:** cuente el efectivo por moneda. El sistema muestra lo esperado y la diferencia; si no cuadra, explique la diferencia en observaciones. El cierre queda en la auditoría.

## Comprobantes electrónicos (SUNAT simulada)

El sistema trae una **SUNAT simulada** que funciona sola, sin configurar nada: recibe cada comprobante, lo valida con las reglas de SUNAT y responde como la real.

1. Desde el folio, **Emitir comprobante**: boleta (DNI, carné, pasaporte o sin documento) o factura (RUC).
2. Elija los cargos a incluir. Se numera con su serie (F001, B001) y se genera el **XML UBL 2.1** con su código hash.
3. SUNAT responde al instante con la **constancia de recepción (CDR)**:

| Respuesta | Qué significa | Qué hacer |
| --- | --- | --- |
| Aceptado (0) | Comprobante válido | Nada |
| Aceptado con observaciones | Válido, pero con avisos (ej. cliente NO HABIDO, sin dirección) | Corregir los datos del cliente para la próxima vez |
| Rechazado | No es válido para SUNAT | Corregir y emitir uno nuevo: los cargos vuelven al folio |
| Pendiente | No hubo conexión | Se reenvía solo, o pulse **Reenviar pendientes** |

Rechazos frecuentes:
- **2020** RUC dado de baja;
- **2108** factura enviada fuera del plazo de 3 días;
- **2642** exportación de servicios a un cliente con DNI o RUC (use pasaporte o carné);
- **2524** nota sobre un comprobante no informado o de baja;
- **1033** número ya informado con otros datos.

En el comprobante puede descargar el **PDF**, el **XML** y el **CDR** (ZIP, como lo entrega SUNAT).

## Notas de crédito y débito

Desde el comprobante aceptado: nota de crédito total (devuelve los cargos al folio) o parcial, y nota de débito. SUNAT verifica que el comprobante modificado esté vigente y que la nota no supere su saldo.

## Baja de comprobantes

Dentro de los 7 días de emitido:
- **Facturas:** se envía una **comunicación de baja (RA)**.
- **Boletas:** van en el **resumen diario (RC)** con estado "anulado".

SUNAT responde con un **ticket** que procesa en unos segundos. Mientras tanto el comprobante queda "Baja en proceso"; el sistema consulta el ticket solo, o pulse **Consultar ticket**. Pasado el plazo, use una nota de crédito.

## Anticipos de reserva

Cuando cobra un adelanto (marcando **adelanto/depósito** en el pago), el folio muestra **Emitir comprobante de anticipo**. Al emitir el comprobante final, el anticipo se **descuenta solo**:
- el XML incluye el anticipo y la deducción;
- el PDF muestra "Anticipos (−)".

## Facturación agrupada (empresas y agencias)

**Facturación → Facturación agrupada**:
1. Elija la empresa o agencia y el periodo.
2. Marque los consumos de sus huéspedes.
3. Emita una sola factura a crédito, con los días de crédito de la empresa y la referencia de cada reserva en el detalle.

## Guías de remisión

Para sacar bienes del hotel (lavandería externa, reparación, devolución a un proveedor, otra sede) use **Facturación → Guías de remisión**:
1. Motivo de traslado, destinatario (o elija un proveedor), partida y llegada con ubigeo, peso y bultos.
2. **Transporte privado:** placa, DNI y licencia del conductor. **Transporte público:** RUC y razón social de la empresa de transportes.
3. Agregue los bienes (puede elegirlos del almacén).
4. **Guardar y enviar a SUNAT.** Responde con un ticket. Si rechaza (por ejemplo, placa inválida), corrija y vuelva a enviar.

## SUNAT simulada y consulta de validez

- **Facturación → SUNAT simulada** muestra las respuestas, los tickets, lo registrado y el botón para enviar el **resumen diario** de boletas que quedaron pendientes por falta de conexión.
- Cualquier persona puede verificar un comprobante en `/consulta-comprobante/` (RUC, tipo, serie, número e importe), como en la consulta de SUNAT. El enlace está impreso en el PDF.

> Todos los comprobantes llevan la leyenda "SIMULACIÓN, SIN VALOR TRIBUTARIO". Es un sistema de enseñanza.

## Cuentas por cobrar

Las empresas con crédito acumulan sus facturas en la cuenta corriente; el estado de cuenta se ve en la ficha de la empresa.
