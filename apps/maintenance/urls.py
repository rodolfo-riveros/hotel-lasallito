from django.urls import path

from . import views

app_name = "maintenance"

urlpatterns = [
    path("", views.wo_list, name="wo_list"),
    path("nueva/", views.wo_create, name="wo_create"),
    path("<int:pk>/", views.wo_detail, name="wo_detail"),
    path("costos/", views.costs, name="costs"),
    path("preventivo/generar/", views.generate, name="generate"),
    *views.asset_crud.urls("activos", "asset"),
    *views.plan_crud.urls("preventivo", "plan"),
]
