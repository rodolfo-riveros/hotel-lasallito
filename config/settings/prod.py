"""Entorno de producción / aula (RNF-SEG-01: HTTPS obligatorio). Preparado para Render."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, BACKUP_UPLOAD, CSRF_TRUSTED_ORIGINS, SECRET_KEY, SENTRY_DSN, env

DEBUG = False

if not SECRET_KEY or SECRET_KEY.startswith("inseguro") or len(SECRET_KEY) < 40:
    raise ImproperlyConfigured(
        "Defina SECRET_KEY (la misma del entorno donde se cargaron los datos: con ella se cifran los "
        "documentos de los huéspedes)."
    )

# Render publica el dominio en RENDER_EXTERNAL_HOSTNAME (ej. hotel-lasallito.onrender.com).
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if RENDER_HOST:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, RENDER_HOST]
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{RENDER_HOST}"]
SITE_URL = env("SITE_URL", default=f"https://{RENDER_HOST}" if RENDER_HOST else "http://127.0.0.1:8000")

# Bloqueo por intentos fallidos con la IP real del usuario, no la del proxy (RNF-SEG-01).
AXES_CLIENT_IP_CALLABLE = "apps.core.middleware.proxied_client_ip"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^sin-conexion/$"]  # chequeo de salud interno de Render
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# El disco del servidor se borra en cada despliegue: el respaldo al cerrar el día solo tiene sentido si
# se sube a Supabase Storage.
BACKUP_ON_NIGHT_AUDIT = env.bool("BACKUP_ON_NIGHT_AUDIT", default=BACKUP_UPLOAD)

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN, send_default_pii=False, traces_sample_rate=0.1)
