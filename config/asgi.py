import os

from django.core.asgi import get_asgi_application

# En Render (variable RENDER) siempre producción: nunca DEBUG, aunque en el panel quede
# DJANGO_SETTINGS_MODULE=config.settings.dev (por ejemplo, al importar un .env de desarrollo).
if os.environ.get("RENDER"):
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_asgi_application()
