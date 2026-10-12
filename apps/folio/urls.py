from django.urls import path

from . import views

app_name = "folio"

urlpatterns = [
    path("", views.folio_list, name="folio_list"),
    path("nuevo/", views.folio_create, name="folio_create"),
    path("<int:pk>/", views.folio_detail, name="folio_detail"),
    path("<int:pk>/<slug:action>/", views.folio_action, name="folio_action"),
    path("caja/", views.cash, name="cash"),
    path("caja/turno/<int:pk>/", views.cash_session, name="cash_session"),
    path("caja/turno/<int:pk>/cerrar/", views.cash_close, name="cash_close"),
    path("cuentas-por-cobrar/", views.receivables, name="receivables"),
    *views.concept_crud.urls("conceptos", "concept"),
    *views.register_crud.urls("cajas", "register"),
]
