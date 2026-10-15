from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("configuracion/hotel/", views.property_settings, name="property_settings"),
    path("configuracion/tipo-de-cambio/", views.exchange_rates, name="exchange_rates"),
    path("configuracion/impuestos/", views.tax_list, name="tax_list"),
    path("configuracion/impuestos/nuevo/", views.tax_edit, name="tax_create"),
    path("configuracion/impuestos/<int:pk>/", views.tax_edit, name="tax_edit"),
    path("auditoria/", views.audit_list, name="audit_list"),
    path("guia-visual/", views.design_system, name="design_system"),
    path("contingencia/", views.offline, name="offline"),
    path("ayuda/", views.help_index, name="help"),
    path("ayuda/<slug:slug>/", views.help_topic, name="help_topic"),
]
