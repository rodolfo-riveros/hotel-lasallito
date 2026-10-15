---
fecha: 2026-10-15
fase: 4
estado: aceptada
tags: [decision, despliegue]
---
# Decisión: despliegue en Render con Supabase

**Contexto.** El usuario quiere publicar el sistema en Render. La base ya está en Supabase (us-west-2).

**Decisión.**
- Blueprint en `render.yaml`:
  - servicio web Python en **Oregon** (cerca de Supabase), gunicorn con 2 procesos y 4 hilos;
  - cron job `run_scheduler` cada 15 minutos.
- `build.sh` instala dependencias, recopila estáticos (WhiteNoise) y aplica migraciones. El CSS y las
  traducciones van compilados en el repositorio, así que no se necesita Node.
- `config/settings/prod.py`:
  - toma el dominio de `RENDER_EXTERNAL_HOSTNAME` para `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` y `SITE_URL`;
  - exige `SECRET_KEY`;
  - HTTPS obligatorio y HSTS;
  - el chequeo de salud `/sin-conexion/` queda exento de la redirección.
- **IP real.** django-axes usa la última entrada de `X-Forwarded-For` (la agrega el proxy de Render), no la
  primera, que el cliente puede falsificar.
- **Archivos y respaldos** a Supabase Storage, porque el disco de Render es efímero. El respaldo al cerrar
  el día se activa solo si hay subida a Storage.

**Riesgo crítico.** Los campos cifrados usan una llave derivada de `SECRET_KEY` (no hay
`FIELD_ENCRYPTION_KEY`). Render debe usar exactamente la misma `SECRET_KEY` del `.env` con que se cargaron
los datos.
