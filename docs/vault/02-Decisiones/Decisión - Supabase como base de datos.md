---
fecha: 2026-10-12
fase: 0
estado: aceptada
tags: [decision, base-de-datos]
---
# Decisión: Supabase como base de datos

**Contexto.** El documento (sección 13) pide PostgreSQL en Supabase. El usuario ya tenía el proyecto
`hotel-la-sallito` (ref `aljafshzuqrmmdezjpiw`, us-east-1), pausado.

**Opciones.**
1. Reactivar `hotel-la-sallito`.
2. Crear un proyecto nuevo.
3. Desarrollar con PostgreSQL local y conectar Supabase después.

**Decisión.** Opción 1, elegida por el usuario. Se reanudó el proyecto el 2026-10-12.

**Limpieza previa.** El proyecto tenía un esquema anterior en español (`hoteles`, `reservas`, `folios`,
`perfiles` sobre `auth.users`, triggers y vistas). Estaba vacío y con RLS desactivado. Se eliminó el
2026-10-12 con la migración `drop_legacy_pms_schema` y se conservó `pg_trgm`.

**Cómo se conecta.**
- Django se conecta por el **pooler en modo sesión (puerto 5432)** con `DATABASE_URL` en `.env` (RF-BD-01, RF-BD-02).
- La migración `core.0003` crea `btree_gist` (RF-BD-03).
- La señal `post_migrate` activa RLS sin políticas en todas las tablas (RF-BD-04). Django entra como dueño
  de las tablas y no se ve afectado.
- El login es el de Django, no se usa Supabase Auth (RF-BD-05).
- Las pruebas **nunca** usan Supabase: usan `TEST_DATABASE_URL` o SQLite en memoria.
- Si `DATABASE_URL` está vacía se usa SQLite, para poder probar sin conexión.
