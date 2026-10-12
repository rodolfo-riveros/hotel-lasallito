"""Control de acceso por rol en cada vista (RNF-SEG-02)."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def user_can(request, perm: str) -> bool:
    user = request.user
    return user.is_authenticated and user.has_pms_perm(getattr(request, "property", None), perm)


def require_perm(perm: str):
    """Decorador: exige el permiso `módulo.acción` en la propiedad activa."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not user_can(request, perm):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapped.required_perm = perm
        return wrapped

    return decorator


class PermRequiredMixin(LoginRequiredMixin):
    required_perm: str = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_can(request, self.required_perm):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
