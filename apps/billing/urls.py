from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("consulta/", views.lookup, name="lookup"),
    path("reenviar/", views.retry_pending, name="retry_pending"),
    path("simulador/", views.simulator, name="simulator"),
    path("ple/", views.ple_export, name="ple"),
    path("<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("<int:pk>/<slug:action>/", views.invoice_action, name="invoice_action"),
    *views.series_crud.urls("series", "series"),
    *views.taxpayer_crud.urls("padron-ruc", "taxpayer"),
    *views.person_crud.urls("padron-dni", "person"),
]
