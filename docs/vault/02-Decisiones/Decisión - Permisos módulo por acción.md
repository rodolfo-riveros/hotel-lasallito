---
fecha: 2026-10-12
fase: 0
estado: aceptada
tags: [decision, seguridad]
---
# Decisión: permisos módulo × acción por propiedad

**Contexto.** RF-SEG-01 pide permisos por módulo y acción. RF-SEG-02 pide un rol distinto por propiedad.

**Opciones.**
1. Permisos y grupos nativos de Django (por modelo, globales).
2. Catálogo propio "módulo.acción" + `Role` + `PropertyAccess(user, property, role)`.

**Decisión.** Opción 2.
- El catálogo único está en `apps/accounts/permissions.py`. De ahí se generan:
  - los permisos en la base (`post_migrate`);
  - la matriz editable de roles;
  - el menú lateral.
- Las vistas usan `@require_perm("reservations.create")`.
- Los 11 roles de la sección 3 se crean con `seed_pms` y luego se pueden editar. Un nuevo `seed_pms` no
  pisa los cambios, salvo con `--reset-roles`.
- `Role` guarda además el tope de descuento (RF-TAR-07) y el límite de aprobación de compras (RF-COM-01).

**Motivo.** Los permisos nativos son globales y por modelo. Lo que se necesita es por propiedad y por
acción de negocio (anular, aprobar, exportar).
