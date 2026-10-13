---
fecha: 2026-10-13
fase: 3
estado: aceptada
tags: [decision, canales, web]
---
# Decisión: channel manager detrás de un adaptador y motor web propio

**Contexto.** RF-CHA pide sincronizar con Booking.com, Expedia, Airbnb y agencias mediante un channel manager
externo. El proveedor aún no está elegido. RF-WEB pide un sitio de reservas propio en tres idiomas y dos monedas.

**Decisión.**
- `apps.channels.adapters` define la interfaz (`push`, `fetch_reservations`). `CHANNEL_MANAGER=test` usa
  `TestChannelManager`, que guarda lo publicado en `ChannelInventory`. `SiteMinderAdapter` queda como esqueleto.
- Cada reserva o bloqueo marca la propiedad como "pendiente de publicar". Se publica:
  - a mano desde el panel;
  - de inmediato con Celery si `CHANNEL_SYNC_ASYNC=true` (requiere Redis);
  - con `run_scheduler`, si hubo cambios o pasó una hora.
- Las reservas entrantes usan el flujo normal (`create_reservation`) con la tarifa que cobró el canal
  (`fixed_nightly_rate`) y el código externo, así bajan la disponibilidad en todos los canales y no se duplican.
- Los errores quedan en `SyncLog`, se reintentan desde el panel y avisan al gerente (RF-CHA-04).
- El motor web (`/reservar/`) es público y reutiliza `quote`, `availability_grid`, `create_reservation` y la
  pasarela de prueba. Si el huésped paga en línea, la reserva queda "pendiente" hasta que la pasarela confirma
  y entonces pasa a "garantizada". Los extras de la venta adicional son los servicios de tours marcados como
  "ofrecer en la web".
- Los bots se frenan con un campo trampa oculto. Hay `robots.txt`, `sitemap.xml` y datos estructurados
  `schema.org/Hotel`.

**Pendiente.** Elegir el channel manager real y completar su adaptador.
