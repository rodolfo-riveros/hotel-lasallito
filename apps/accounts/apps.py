from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Usuarios y permisos"

    def ready(self):
        from . import signals  # noqa: F401

        post_migrate.connect(_sync_after_migrate, sender=self)


def _sync_after_migrate(sender, **kwargs):
    from .services import sync_permissions

    sync_permissions(using=kwargs.get("using", "default"))
