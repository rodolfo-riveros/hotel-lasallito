---
fase: 3
estado: vigente
tags: [modelo-de-datos]
---
# Modelo de datos de la fase 3

```mermaid
erDiagram
    Channel ||--o{ RoomMapping : "tipos"
    Channel ||--o{ RateMapping : "planes + recargo"
    Channel ||--o{ SyncLog : "envíos y recepciones"
    Channel ||--o{ ChannelInventory : "lo publicado"
    RoomMapping }o--|| RoomType : ""
    RateMapping }o--|| RatePlan : ""
    Channel }o--o| Company : "factura la comisión"
    Operator ||--o{ Service : "tours y traslados"
    Service ||--o{ ServiceBooking : "ventas"
    ServiceBooking }o--o| Reservation : ""
    ServiceBooking }o--o| Charge : "cargo en el folio"
    Guest ||--o{ LoyaltyTransaction : "puntos"
    LoyaltyTransaction }o--|| Property : "hotel donde se ganó o canjeó"
    LoyaltyTier
    GroupRequest }o--|| Property : "solicitud web"
    ScenarioRun }o--|| Property : "escenario de práctica"
    PracticeEvent }o--|| Property : "evento del docente"
```

## Apps y tablas
- **`pms_channels`** (app `apps.channels`; la etiqueta evita chocar con el paquete `channels` de Django):
  `Channel`, `RoomMapping`, `RateMapping`, `SyncLog`, `ChannelInventory`.
- **`tours`**: `Operator`, `Service` (nombres en es/en/pt, precio y costo por persona), `ServiceBooking`
  (guarda precio y costo del momento de la venta).
- **`booking_engine`**: `GroupRequest`. Las reservas web son `Reservation` con `channel="web"`.
- **`guests`**: `LoyaltyTier` y `LoyaltyTransaction`. Son de la cadena, como `Guest` (RF-MUL-03), por eso no
  heredan `PropertyScopedModel`; cada movimiento guarda en qué hotel ocurrió.
- **`folio`**: nuevo medio de pago `points` (canje de puntos).
- **`classroom`**: `ScenarioRun` (datos del escenario en JSON) y `PracticeEvent`.

Ver también [[fase-1]], [[fase-2]], [[Decisión - Channel manager y motor web]] y [[Decisión - Modo aula]].
