---
fecha: 2026-10-12
fase: 0
estado: aceptada
tags: [decision, seguridad, auditoria]
---
# Decisión: auditoría inmutable en dos capas

**Contexto.** RNF-SEG-03 pide una auditoría inmutable de acciones críticas, con usuario, fecha, IP y valor
anterior.

**Decisión.**
- **Modelo** `AuditLog`: `save()` solo inserta; `update()` y `delete()` lanzan error.
- **Base de datos** (PostgreSQL): el trigger `core_auditlog_immutable` rechaza UPDATE y DELETE incluso con
  SQL directo.
- **Contexto de la petición** (`contextvars`): captura usuario, IP y navegador sin tener que pasarlos a mano.
- **Servicio** `apps.core.audit`:
  - `log()` registra una acción;
  - `log_changes()` guarda solo los campos que cambiaron, con su valor anterior y el nuevo, releídos de la base.
- Se auditan:
  - inicio y cierre de sesión, e intentos fallidos;
  - cambios de permisos y de usuarios;
  - impuestos, tipo de cambio y configuración del hotel;
  - exportaciones.
