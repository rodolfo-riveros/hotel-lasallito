"""Contexto de la petición actual (usuario, IP, propiedad) para auditoría.

Usa `contextvars`, seguro tanto en hilos como en código asíncrono.
"""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestInfo:
    user: object | None = None
    ip_address: str | None = None
    user_agent: str = ""
    property_id: int | None = None


_EMPTY = RequestInfo()  # dataclass congelada: es inmutable
_current: ContextVar[RequestInfo] = ContextVar("pms_request_info", default=_EMPTY)


def set_request_info(info: RequestInfo):
    return _current.set(info)


def reset_request_info(token) -> None:
    _current.reset(token)


def get_request_info() -> RequestInfo:
    return _current.get()


def get_current_user():
    user = _current.get().user
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


def update_request_info(**changes) -> None:
    """Completa el contexto actual (por ejemplo con la propiedad activa)."""
    from dataclasses import replace

    _current.set(replace(_current.get(), **changes))
