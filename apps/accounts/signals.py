"""Auditoría de accesos: inicio, cierre y fallos de sesión (RNF-SEG-03)."""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.core import audit
from apps.core.models import AuditLog


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.log(AuditLog.Action.LOGIN, user, user=user, property=user.default_property)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        audit.log(AuditLog.Action.LOGOUT, user, user=user, property=getattr(request, "property", None))


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get("username", "")[:150]
    audit.log(AuditLog.Action.LOGIN_FAILED, None, changes={"username": username})


# --------------------------------------------------------------------------
# Invalidación de la caché de permisos (RNF-REN-01)
# --------------------------------------------------------------------------
from django.db.models.signals import m2m_changed, post_delete, post_save  # noqa: E402

from .cache import bump_version  # noqa: E402


def _invalidate(sender, **kwargs):
    bump_version()


def connect_cache_signals():
    from apps.core.models import Property

    from .models import PropertyAccess, Role, User

    for model in (Role, PropertyAccess, Property, User):
        post_save.connect(_invalidate, sender=model, dispatch_uid=f"pms_cache_save_{model.__name__}")
        post_delete.connect(_invalidate, sender=model, dispatch_uid=f"pms_cache_del_{model.__name__}")
    m2m_changed.connect(_invalidate, sender=Role.permissions.through, dispatch_uid="pms_cache_m2m")
