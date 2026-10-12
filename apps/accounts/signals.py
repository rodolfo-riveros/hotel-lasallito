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
