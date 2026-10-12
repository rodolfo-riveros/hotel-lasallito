from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("cuenta/", include("apps.accounts.urls")),
    path("recepcion/", include("apps.frontdesk.urls")),
    path("reservas/", include("apps.reservations.urls")),
    path("habitaciones/", include("apps.rooms.urls")),
    path("tarifas/", include("apps.rates.urls")),
    path("huespedes/", include("apps.guests.urls")),
    path("folios/", include("apps.folio.urls")),
    path("facturacion/", include("apps.billing.urls")),
    path("housekeeping/", include("apps.housekeeping.urls")),
    path("restaurante/", include("apps.pos.urls")),
    path("reportes/", include("apps.reports.urls")),
    path("comunicaciones/", include("apps.comms.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
