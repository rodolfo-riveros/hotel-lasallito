"""Servicio de auditoría (RNF-SEG-03).

Uso:
    audit.log(AuditLog.Action.RATE_CHANGE, obj, changes={"rate": [old, new]}, reason="...")
    audit.log_changes(obj, before_dict)   # registra solo los campos que cambiaron
"""

from decimal import Decimal

from django.forms.models import model_to_dict

from .models import AuditLog
from .request_context import get_request_info


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj, fields=None) -> dict:
    """Foto de los campos editables de un objeto, lista para comparar."""
    data = model_to_dict(obj, fields=fields)
    return {k: _jsonable(v) for k, v in data.items()}


def diff(before: dict, after: dict) -> dict:
    return {
        key: [before.get(key), after.get(key)]
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }


def log(action, obj=None, *, changes=None, reason="", user=None, property=None) -> AuditLog:
    info = get_request_info()
    user = user if user is not None else info.user
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None
    if property is None and obj is not None:
        property = getattr(obj, "property", None)
        if property is None and obj.__class__.__name__ == "Property":
            property = obj
    property_id = getattr(property, "pk", None) or info.property_id
    return AuditLog.objects.create(
        user=user,
        username=getattr(user, "username", "") if user else "",
        property_id=property_id,
        action=action,
        object_type=obj._meta.label if obj is not None else "",
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        object_repr=str(obj)[:255] if obj is not None else "",
        changes={k: _jsonable(v) for k, v in (changes or {}).items()},
        reason=reason[:255],
        ip_address=info.ip_address,
        user_agent=info.user_agent,
    )


def log_changes(obj, before: dict, *, action=AuditLog.Action.UPDATE, reason="") -> AuditLog | None:
    # Se relee de la base para comparar los valores tal como quedaron guardados
    # (por ejemplo, Decimal con su escala real: 3.74 -> 3.7400).
    obj.refresh_from_db(fields=list(before))
    changes = diff(before, snapshot(obj, fields=list(before)))
    if not changes:
        return None
    return log(action, obj, changes=changes, reason=reason)
