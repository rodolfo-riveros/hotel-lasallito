"""Configuración base del PMS Hotel La Sallito.

Todo valor sensible o dependiente del entorno se lee de variables de entorno
(RNF-SEG-07, RF-BD-01). Ver `.env.example`.
"""

from decimal import Decimal
from pathlib import Path

import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SUNAT_MODE=(str, "simulator"),
    SESSION_IDLE_SECONDS=(int, 1800),
    AXES_FAILURE_LIMIT=(int, 5),
    AXES_COOLOFF_MINUTES=(int, 15),
    DB_CONN_MAX_AGE=(int, 60),
    DB_DISABLE_SERVER_SIDE_CURSORS=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="inseguro-solo-para-desarrollo-cambiar")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# --------------------------------------------------------------------------
# Aplicaciones
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
]
THIRD_PARTY_APPS = [
    "axes",
    "django_htmx",
    "django_countries",
]
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.rooms",
    "apps.rates",
    "apps.guests",
    "apps.reservations",
    "apps.folio",
    "apps.billing",
    "apps.frontdesk",
    "apps.housekeeping",
    "apps.pos",
    "apps.comms",
    "apps.reports",
    "apps.inventory",
    "apps.purchasing",
    "apps.maintenance",
    "apps.payments",
    "apps.portal",
    "apps.channels",
    "apps.booking_engine",
    "apps.tours",
    "apps.classroom",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "apps.accounts.middleware.IdleTimeoutMiddleware",
    "apps.accounts.middleware.CurrentPropertyMiddleware",
    # axes debe ir al final (documentación de django-axes).
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.core.context_processors.pms",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Base de datos: PostgreSQL en Supabase (sección 13)
# --------------------------------------------------------------------------
DATABASES = {
    "default": env.db_url_config(
        env("DATABASE_URL", default="") or f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}"
    ),
}
DATABASES["default"]["CONN_MAX_AGE"] = env("DB_CONN_MAX_AGE")
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"]["ATOMIC_REQUESTS"] = False
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    # RF-BD-02: con el pooler en modo transacción (puerto 6543) se desactivan
    # los cursores del lado del servidor.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = env("DB_DISABLE_SERVER_SIDE_CURSORS")
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("sslmode", env("DB_SSLMODE", default="require"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------
# Autenticación y seguridad (RNF-SEG-01)
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.CachedModelBackend",
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# Bloqueo tras intentos fallidos (django-axes)
AXES_FAILURE_LIMIT = env("AXES_FAILURE_LIMIT")
AXES_COOLOFF_TIME = env("AXES_COOLOFF_MINUTES") / 60  # horas
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked.html"

# Sesión firmada en cookie: no consulta la base en cada página (RNF-REN-01).
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "pms"}}

# Cierre de sesión por inactividad
SESSION_IDLE_SECONDS = env("SESSION_IDLE_SECONDS")
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # HTMX lee el token desde la cookie
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# --------------------------------------------------------------------------
# Idiomas y localización (RNF-I18N)
# --------------------------------------------------------------------------
LANGUAGE_CODE = "es"
LANGUAGES = [
    ("es", _("Español")),
    ("en", _("English")),
    ("pt-br", _("Português")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
# El personal opera en Perú: los montos usan punto decimal en todos los idiomas.
FORMAT_MODULE_PATH = ["config.formats"]
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Archivos estáticos y de medios
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# RF-BD-06: Supabase Storage es compatible con S3. Se activa si hay credenciales.
SUPABASE_S3_ENDPOINT = env("SUPABASE_S3_ENDPOINT", default="")
if SUPABASE_S3_ENDPOINT:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": SUPABASE_S3_ENDPOINT,
            "access_key": env("SUPABASE_S3_ACCESS_KEY"),
            "secret_key": env("SUPABASE_S3_SECRET_KEY"),
            "bucket_name": env("SUPABASE_S3_BUCKET", default="pms-media"),
            "region_name": env("SUPABASE_S3_REGION", default="us-east-1"),
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
        },
    }

# --------------------------------------------------------------------------
# Celery / Redis (RNF-REN-04)
# --------------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_BEAT_SCHEDULE = {
    "pms-scheduler": {"task": "apps.core.tasks.run_scheduler_task", "schedule": 15 * 60},
}

# --------------------------------------------------------------------------
# Correo
# --------------------------------------------------------------------------
EMAIL_CONFIG = env.email("EMAIL_URL", default="consolemail://")
globals().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Hotel La Sallito <no-reply@localhost>")

# --------------------------------------------------------------------------
# Propio del PMS
# --------------------------------------------------------------------------
# RNF-SEG-04: llave de cifrado de pasaportes y datos de salud (Fernet, base64 de 32 bytes).
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")
# Sección 12: "simulator" o "production". Solo afecta la facturación SUNAT.
SUNAT_MODE = env("SUNAT_MODE")
# Pasarela de pagos (sección 9): "test" hasta que el hotel elija Izipay, Niubiz o Culqi.
PAYMENT_GATEWAY = env("PAYMENT_GATEWAY", default="test")
# WhatsApp Business Cloud API (RF-COMU-01). Sin credenciales, modo prueba.
WHATSAPP_TOKEN = env("WHATSAPP_TOKEN", default="")
WHATSAPP_PHONE_ID = env("WHATSAPP_PHONE_ID", default="")
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="")
# Channel manager (sección 9): "test" hasta elegir SiteMinder, Cloudbeds u otro.
CHANNEL_MANAGER = env("CHANNEL_MANAGER", default="test")
# True solo si hay Redis y un worker de Celery: publica en los canales segundos después de cada cambio.
CHANNEL_SYNC_ASYNC = env.bool("CHANNEL_SYNC_ASYNC", default=False)
# URL pública del sistema, usada en los enlaces de correos y del portal.
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000")

# --------------------------------------------------------------------------
# Registros (RNF-MAN-05)
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}

SENTRY_DSN = env("SENTRY_DSN", default="")

# Fidelidad (RF-HUE-04): puntos por cada sol consumido y valor de canje de cada punto.
LOYALTY_POINTS_PER_PEN = Decimal(env("LOYALTY_POINTS_PER_PEN", default="0.1"))
LOYALTY_PEN_PER_POINT = Decimal(env("LOYALTY_PEN_PER_POINT", default="0.10"))
