"""Campos cifrados en reposo (RNF-SEG-04).

`EncryptedTextField` guarda el texto cifrado con Fernet (AES-128 + HMAC). La
llave sale de FIELD_ENCRYPTION_KEY o, si no existe, se deriva de SECRET_KEY.
Para buscar por documento sin descifrar se usa `blind_index()` (HMAC-SHA256).
"""

import base64
import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

PREFIX = "enc$"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    if not key:
        digest = hashlib.sha256(("pms-field-key:" + settings.SECRET_KEY).encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    if value in (None, ""):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value or not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        return ""


def blind_index(value: str) -> str:
    normalized = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    if not normalized:
        return ""
    return hmac.new(settings.SECRET_KEY.encode(), normalized.encode(), hashlib.sha256).hexdigest()


class EncryptedTextField(models.TextField):
    def from_db_value(self, value, expression, connection):
        return decrypt(value)

    def to_python(self, value):
        return decrypt(value) if isinstance(value, str) else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, "") or (isinstance(value, str) and value.startswith(PREFIX)):
            return value
        return encrypt(value)
