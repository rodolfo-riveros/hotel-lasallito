from django.urls import path

from . import views

app_name = "tours"

urlpatterns = [
    path("", views.agenda, name="agenda"),
    path("vender/", views.sell, name="sell"),
    path("liquidacion/", views.settlement, name="settlement"),
    *views.service_crud.urls("catalogo", "service"),
    *views.operator_crud.urls("operadores", "operator"),
]
