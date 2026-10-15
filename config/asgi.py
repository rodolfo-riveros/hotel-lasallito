import os

from django.core.asgi import get_asgi_application

# En Render (variable RENDER) siempre producción, aunque falte DJANGO_SETTINGS_MODULE: nunca DEBUG.
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "config.settings.prod" if os.environ.get("RENDER") else "config.settings.dev"
)
application = get_asgi_application()
