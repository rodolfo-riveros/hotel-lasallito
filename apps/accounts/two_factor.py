"""Doble factor con app autenticadora (TOTP, RFC 6238) — RF-SEG-03.

Compatible con Google Authenticator, Microsoft Authenticator, Authy y similares. Cada código
sirve una sola vez (`totp_last_step`), y activar, desactivar o reiniciar el doble factor queda
en la auditoría.
"""

import io
import time

import pyotp
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog

PERIOD = 30


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(user, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=settings.TWO_FACTOR_ISSUER)


def qr_svg(uri: str) -> str:
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def _matching_step(secret: str, code: str, at: float | None = None) -> int | None:
    """Paso de tiempo del código si es válido (acepta ±1 paso por desfase del reloj)."""
    code = "".join(c for c in str(code) if c.isdigit())
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = at if at is not None else time.time()
    for offset in (0, -1, 1):
        moment = now + offset * PERIOD
        if totp.verify(code, for_time=moment, valid_window=0):
            return int(moment // PERIOD)
    return None


def verify(user, code: str, at: float | None = None) -> bool:
    """Valida el código del usuario y lo marca como usado."""
    if not user.totp_enabled or not user.totp_secret:
        return False
    step = _matching_step(user.totp_secret, code, at)
    if step is None or step <= user.totp_last_step:
        return False
    type(user).objects.filter(pk=user.pk).update(totp_last_step=step)
    user.totp_last_step = step
    return True


def enable(user, secret: str, code: str, at: float | None = None):
    step = _matching_step(secret, code, at)
    if step is None:
        raise ValidationError(_("El código no es válido. Revise la hora del celular e intente de nuevo."))
    user.totp_secret, user.totp_enabled, user.totp_last_step = secret, True, step
    user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
    audit.log(
        AuditLog.Action.PERMISSION,
        user,
        changes={"doble_factor": "activado"},
        user=user,
        property=user.default_property,
    )


def disable(user, by, reason=""):
    user.totp_secret, user.totp_enabled, user.totp_last_step = "", False, 0
    user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
    audit.log(
        AuditLog.Action.PERMISSION,
        user,
        changes={"doble_factor": "desactivado"},
        user=by,
        reason=reason,
        property=user.default_property,
    )


def required_for(user) -> bool:
    roles = set(settings.TWO_FACTOR_REQUIRED_ROLES)
    if not roles:
        return False
    return user.property_accesses.filter(is_active=True, role__code__in=roles).exists()
