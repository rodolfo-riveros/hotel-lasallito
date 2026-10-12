import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect, resolve_url
from django.utils.translation import gettext as _

from apps.core.request_context import update_request_info

SESSION_PROPERTY_KEY = "pms_property_id"
SESSION_ACTIVITY_KEY = "pms_last_activity"


class IdleTimeoutMiddleware:
    """Cierra la sesión tras un tiempo sin actividad (RNF-SEG-01)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = int(time.time())
            last = request.session.get(SESSION_ACTIVITY_KEY, now)
            if now - last > settings.SESSION_IDLE_SECONDS:
                logout(request)
                messages.info(request, _("Tu sesión se cerró por inactividad."))
                if getattr(request, "htmx", False):
                    response = HttpResponse(status=204)
                    response["HX-Redirect"] = resolve_url(settings.LOGIN_URL)
                    return response
                return redirect(settings.LOGIN_URL)
            if now - last >= 60 or SESSION_ACTIVITY_KEY not in request.session:
                # Se actualiza como máximo una vez por minuto para no reescribir la sesión.
                request.session[SESSION_ACTIVITY_KEY] = now
        return self.get_response(request)


class CurrentPropertyMiddleware:
    """Fija `request.property`: la propiedad con la que trabaja el usuario."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.property = None
        request.user_properties = []
        user = request.user
        if user.is_authenticated:
            from .cache import properties_for

            properties = properties_for(user)
            request.user_properties = properties
            by_id = {p.pk: p for p in properties}
            chosen = by_id.get(request.session.get(SESSION_PROPERTY_KEY))
            if chosen is None and user.default_property_id in by_id:
                chosen = by_id[user.default_property_id]
            if chosen is None and properties:
                chosen = properties[0]
            request.property = chosen
            if chosen is not None:
                if request.session.get(SESSION_PROPERTY_KEY) != chosen.pk:
                    request.session[SESSION_PROPERTY_KEY] = chosen.pk
                update_request_info(property_id=chosen.pk, user=user)
        return self.get_response(request)
