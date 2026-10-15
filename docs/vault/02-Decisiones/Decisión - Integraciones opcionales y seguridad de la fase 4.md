---
fecha: 2026-10-15
fase: 4
estado: aceptada
tags: [decision, integraciones, seguridad]
---
# Decisión: integraciones opcionales, doble factor y respaldos

**Cerraduras y central telefónica.** Van detrás de adaptadores, como SUNAT y los pagos:
- `DOOR_LOCK=test|salto|none`;
- `PBX=test|none`, con `PBX_TOKEN` y `PBX_RATES`.

Funcionamiento:
- Las tarjetas se graban en el check-in, se regraban en el cambio de habitación (las anteriores se anulan)
  y se anulan en el check-out.
- Si el codificador falla, el check-in sigue y recepción recibe un aviso.
- La central envía cada llamada (CDR) a un webhook con token. Se clasifica según el plan de numeración del
  Perú, se tarifa por minuto iniciado y se carga al folio de la habitación con el número parcialmente oculto.
- Una llamada repetida no se cobra dos veces.

**Doble factor (RF-SEG-03).**
- TOTP compatible con Google/Microsoft Authenticator.
- El secreto se guarda cifrado y cada código sirve una sola vez.
- La sesión recién se abre al validar el código. Cinco códigos errados obligan a ingresar de nuevo.
- Es opcional por defecto; `TWO_FACTOR_REQUIRED_ROLES` lo vuelve obligatorio para los roles que se indiquen.
- El administrador puede reiniciarlo. Todo queda en la auditoría.

**Respaldos (RF-REC-13, RNF-DIS-02).**
- `dumpdata` comprimido y verificado al cerrar el día y una vez al día con el programador.
- Se conservan 30 días. Hay copia opcional a Supabase Storage.
- No reemplaza los respaldos propios de Supabase: es la copia fuera del proveedor.

**Conservación de datos (RNF-SEG-06).** Cada mes se anonimiza a quien no tiene estadías en
`GUEST_RETENTION_YEARS` (5 años por defecto).

**Manual (RNF-MAN-03, RNF-UX-07).**
- Vive en `docs/manual/` y se ve dentro del sistema en `/ayuda/`, con un botón "Ayuda" que abre el capítulo
  de la pantalla.
- El conversor de Markdown escapa todo el HTML.
