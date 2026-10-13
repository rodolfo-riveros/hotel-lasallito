from django.apps import AppConfig


class ChannelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.channels"
    label = "pms_channels"  # evita choque con el paquete "channels" (Django Channels)
    verbose_name = "Channel manager"

    def ready(self):
        from . import signals  # noqa: F401
