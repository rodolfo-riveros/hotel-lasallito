import os

from django.core.wsgi import get_wsgi_application

# En Render (variable RENDER) siempre producción, aunque falte DJANGO_SETTINGS_MODULE: nunca DEBUG.
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "config.settings.prod" if os.environ.get("RENDER") else "config.settings.dev"
)
application = get_wsgi_application()
