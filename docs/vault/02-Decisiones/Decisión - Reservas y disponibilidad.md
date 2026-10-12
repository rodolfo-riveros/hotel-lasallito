---
fecha: 2026-10-12
fase: 1
estado: aceptada
tags: [decision, reservas]
---
# Decisión: una reserva = una habitación

**Contexto.** El documento propone Reservation, ReservationRoom, GroupBlock y Stay.

**Decisión.**
- Cada `Reservation` ocupa una habitación, o solo un tipo mientras no se asigne.
- Los grupos (`GroupBlock`) agrupan varias reservas y reservan cupos por tipo hasta su fecha de liberación.
- No hay tabla `Stay`: la propia reserva (`room`, `arrival`, `departure`) es la estadía.
- La regla "una habitación no puede tener dos estadías solapadas" vive en PostgreSQL. La restricción de
  exclusión `reservation_room_no_overlap` (btree_gist) se verificó en Supabase el 2026-10-12.
- En el código, la disponibilidad por tipo se calcula noche a noche y bloquea las filas de `RoomType` de la
  propiedad (`select_for_update`). Así dos recepcionistas no venden la misma habitación (RNF-INT-02).
- La sobreventa solo es posible con aprobación del gerente y hasta `overbooking_limit`, y avisa al gerente.
- Un cambio de habitación mueve toda la estadía y deja historial en `RoomMove`. El folio se conserva.

**Motivo.** Es más simple de enseñar y de operar en un hotel pequeño. La restricción en la base da la garantía real.
