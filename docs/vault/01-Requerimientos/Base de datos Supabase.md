---
fase: 0
estado: en curso
tags: [requerimientos, modulo]
---
# Base de datos Supabase

Requerimientos `RF-BD` del [[Documento de requerimientos]]. Fase prevista: 0.

- [x] **RF-BD-01** la conexión se configura con una variable de entorno (`DATABASE_URL`) en un archivo `.env`; la contraseña nunca se sube al repositorio. — DATABASE_URL en .env ✅ fase 0
- [x] **RF-BD-02** se usa el pooler de Supabase en modo sesión (puerto 5432), que funciona bien con Django; si se usa el modo transacción (puerto 6543) hay que desactivar los cursores del lado del servidor. — pooler modo sesión; opción DB_DISABLE_SERVER_SIDE_CURSORS ✅ fase 0
- [x] **RF-BD-03** se habilita la extensión `btree_gist` para la restricción que impide reservas solapadas en la misma habitación. — migración core.0003 crea btree_gist ✅ fase 0
- [x] **RF-BD-04** se activa RLS (seguridad por filas) en todas las tablas, sin políticas, para que nadie pueda leerlas por la API pública de Supabase; Django entra con su rol de servidor y no se ve afectado. — post_migrate activa RLS en todas las tablas ✅ fase 0
- [x] **RF-BD-05** el inicio de sesión sigue siendo el de Django (usuarios y roles propios); no se usa Supabase Auth en esta versión. — login propio de Django ✅ fase 0
- [ ] **RF-BD-06** las fotos y documentos de práctica se guardan en Supabase Storage. — 🟡 parcial: hecho: almacenamiento S3 de Supabase configurable; falta crear bucket
- [ ] **RF-BD-07** un proyecto Supabase de desarrollo y otro de producción o aula, con respaldos automáticos activados. — 🟡 parcial: hecho: proyecto de desarrollo; falta proyecto de producción/aula
