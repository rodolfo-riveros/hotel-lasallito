from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("consulta/", views.lookup, name="lookup"),
    path("reenviar/", views.retry_pending, name="retry_pending"),
    path("sunat/", views.sunat_panel, name="sunat"),
    path("sunat/ticket/<str:number>/cdr/", views.ticket_cdr, name="ticket_cdr"),
    path("ple/", views.ple_export, name="ple"),
    path("agrupada/", views.grouped, name="grouped"),
    path("anticipo/<int:folio_pk>/", views.advance, name="advance"),
    path("guias/", views.guide_list, name="guide_list"),
    path("guias/nueva/", views.guide_edit, name="guide_create"),
    path("guias/<int:pk>/", views.guide_detail, name="guide_detail"),
    path("guias/<int:pk>/editar/", views.guide_edit, name="guide_edit"),
    path("guias/<int:pk>/<slug:kind>/", views.guide_file, name="guide_file"),
    path("<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("<int:pk>/archivo/<slug:kind>/", views.invoice_file, name="invoice_file"),
    path("<int:pk>/<slug:action>/", views.invoice_action, name="invoice_action"),
    *views.series_crud.urls("series", "series"),
    *views.taxpayer_crud.urls("padron-ruc", "taxpayer"),
    *views.person_crud.urls("padron-dni", "person"),
]
