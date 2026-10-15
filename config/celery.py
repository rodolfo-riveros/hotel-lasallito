import os

from celery import Celery

# En Render (variable RENDER) siempre producción, aunque falte DJANGO_SETTINGS_MODULE: nunca DEBUG.
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "config.settings.prod" if os.environ.get("RENDER") else "config.settings.dev"
)

app = Celery("pms")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
