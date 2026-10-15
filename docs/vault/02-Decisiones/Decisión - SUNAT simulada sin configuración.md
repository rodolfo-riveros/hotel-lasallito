---
fecha: 2026-10-15
fase: 4
estado: aceptada
tags: [decision, facturacion, sunat]
---
# Decisión: una SUNAT simulada que valida y responde sola

**Contexto.** El simulador anterior aceptaba todo. Solo fallaba si el docente lo configuraba
("rechazar los próximos N", "caída de conexión"). El usuario pidió que funcione como SUNAT, internamente
y sin configuración.

**Decisión.** `apps/billing/sunat.py` (`SimulatorAdapter`) es una SUNAT interna:
- **Recepción del XML.** Cada comprobante se genera en **XML UBL 2.1** (`apps/billing/ubl.py`) con firma
  simulada; el `DigestValue` es el código hash. SUNAT recalcula el hash: si el XML fue alterado, responde **2335**.
- **Validaciones reales**, con códigos del catálogo de errores (mensajes simplificados):
  - serie según tipo (1001);
  - plazo de 3 días para facturas (2108);
  - receptor RUC válido y activo en el padrón (2017, 2020, 2800);
  - IGV de cada línea y totales (3111, 3105);
  - exportación solo a documento de no domiciliado (2642);
  - notas: comprobante informado y vigente, y saldo (2524, 2525);
  - duplicados (1033).
- **Observaciones**, que se aceptan con aviso: receptor NO HABIDO (4001) y factura sin dirección (4095).
- **Respuesta síncrona** con **CDR** (ApplicationResponse, descargable en ZIP) para facturas, boletas y notas.
- **Envíos con ticket** que se procesan en `SUNAT_TICKET_SECONDS` (15 s) y se consultan con `get_status`,
  igual que en SUNAT:
  - resumen diario (RC);
  - comunicación de baja (RA) para facturas;
  - baja de boletas por RC con estado 3;
  - guía de remisión (GRE).

  El programador y la pantalla consultan los tickets.
- **Registro del lado de SUNAT.** `SunatRegistry` guarda lo recibido: detecta duplicados y alimenta la
  consulta pública de validez (`/consulta-comprobante/`).
- **Reloj.** La SUNAT simulada usa la fecha hotelera, para que las prácticas con fechas pasadas sean coherentes.
- **Padrón.** Un RUC con dígito verificador válido que no figure en el padrón ficticio se considera
  ACTIVO/HABIDO, así no hay que cargar empresas para practicar.

**Qué se quitó.** El formulario del docente para forzar rechazos. La única falla externa que queda es la
caída de conexión del evento "Falla SUNAT" del modo aula.

**RF-FAC-06.**
- Anticipos: comprobante por el adelanto cobrado, deducido en el comprobante final (`PrepaidPayment` y
  descuento global 04 en el XML).
- Facturación agrupada a crédito por empresa o agencia y periodo.

**RF-FAC-09.** Guía de remisión electrónica remitente (DespatchAdvice):
- motivos del catálogo 20 y transporte público o privado;
- validaciones de placa, conductor, transportista, ubigeo, peso y motivo 04;
- PDF con QR.

**Producción.** `SUNAT_MODE=production` usará `OSEAdapter` con la misma interfaz (`send`, `send_summary`,
`send_voided`, `send_despatch`, `get_status`).
