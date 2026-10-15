from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.billing import views as billing_views
from apps.core import pwa

urlpatterns = [
    path("manifest.webmanifest", pwa.manifest, name="pwa_manifest"),
    path("sw.js", pwa.service_worker, name="pwa_sw"),
    path("sin-conexion/", pwa.offline_shell, name="pwa_offline"),
    path("consulta-comprobante/", billing_views.validity_check, name="cpe_validity"),
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
    path("almacen/", include("apps.inventory.urls")),
    path("compras/", include("apps.purchasing.urls")),
    path("mantenimiento/", include("apps.maintenance.urls")),
    path("pagos/", include("apps.payments.urls")),
    path("canales/", include("apps.channels.urls")),
    path("tours/", include("apps.tours.urls")),
    path("aula/", include("apps.classroom.urls")),
    path("integraciones/", include("apps.integrations.urls")),
    path("", include("apps.booking_engine.urls")),
    path("", include("apps.portal.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
