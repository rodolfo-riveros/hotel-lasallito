---
fecha: 2026-10-12
fase: 1
estado: aceptada
tags: [decision, facturacion, sunat]
---
# Decisión: facturación SUNAT detrás de un adaptador

- `apps/billing/sunat.py` define `SunatAdapter`:
  - `SimulatorAdapter` se usa cuando `SUNAT_MODE=simulator`;
  - `OSEAdapter` (Nubefact, Efact...) queda pendiente para producción.
- Validaciones reales:
  - RUC con dígito verificador (módulo 11);
  - DNI en boletas mayores a S/ 700;
  - factura solo con RUC;
  - plazo de 7 días para la baja.
- Exoneración a no domiciliados: afectación **40 (exportación de servicios)** con la leyenda 2005. Requiere
  pasaporte, residencia fuera del Perú y fecha de ingreso (TAM), validados en el check-in y registrados en la
  auditoría.
- Numeración correlativa: se bloquea la `Series` dentro de la transacción. Si el simulador "no tiene
  conexión", el comprobante conserva su número y queda **pendiente** (RNF-DIS-04); un botón lo reenvía.
- El docente controla caídas y rechazos en **Facturación → Simulador SUNAT**.
- PDF con QR, hash y marca de agua "SIMULACIÓN, SIN VALOR TRIBUTARIO" (RF-SIM-06).
- PLE 14.1 con formato real; el archivo se marca como `_EJEMPLO`.
