---
fase: 4
estado: vigente
tags: [modelo-de-datos]
---
# Modelo de datos de la fase 4

```mermaid
erDiagram
    Reservation ||--o{ KeyCard : "tarjetas grabadas"
    KeyCard }o--|| Room : ""
    Reservation ||--o{ CallRecord : "llamadas"
    CallRecord }o--o| Charge : "cargo en el folio"
    CallRecord }o--o| Room : "anexo"
    ReportSubscription }o--|| Property : "envío programado"
    User {
        bool totp_enabled
        text totp_secret "cifrado"
        bigint totp_last_step "evita reusar códigos"
    }
```

## Cambios
- **`accounts.User`**: `totp_secret` (cifrado con Fernet), `totp_enabled`, `totp_last_step` (RF-SEG-03).
- **`integrations`** (app nueva):
  - `KeyCard`: tarjeta grabada por el adaptador de cerradura, con su vigencia;
  - `CallRecord`: registro de la central, con `external_id` único por hotel para no cobrar dos veces.
- **`reports.ReportSubscription`**: reporte, destinatarios, frecuencia, formato y último envío (RF-REP-06).
- **`folio.Charge.Source`**: nuevo origen `phone`.
- **Índices** (RNF-REN-01/02):
  - `res_prop_departure` (propiedad, salida) en reservas;
  - en PostgreSQL, índices de trigramas `pg_trgm` en nombres de huésped y código de reserva.

Ver también [[fase-3]] y [[Decisión - Rendimiento con historial grande]].
