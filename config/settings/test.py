"""Entorno de pruebas automáticas.

Nunca usa la base de Supabase: toma TEST_DATABASE_URL (PostgreSQL local en
Docker o en CI) y, si no existe, SQLite en memoria.
"""

from .base import *  # noqa: F401,F403
from .base import env

DATABASES = {"default": env.db_url_config(env("TEST_DATABASE_URL", default="") or "sqlite://:memory:")}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
STORAGES["default"] = {"BACKEND": "django.core.files.storage.InMemoryStorage"}  # noqa: F405
AXES_ENABLED = True

WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
