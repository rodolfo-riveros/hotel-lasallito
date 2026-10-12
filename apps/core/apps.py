from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Núcleo"

    def ready(self):
        # Se conecta sin `sender` para correr una vez por cada app migrada y
        # cubrir también las tablas de apps que se agreguen después.
        post_migrate.connect(_enable_rls, dispatch_uid="pms_enable_rls")


def _enable_rls(sender, using="default", **kwargs):
    from .db import enable_rls_on_all_tables

    enable_rls_on_all_tables(using=using)
