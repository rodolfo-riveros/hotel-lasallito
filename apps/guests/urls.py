from django.urls import path

from . import views

app_name = "guests"

urlpatterns = [
    path("", views.guest_list, name="guest_list"),
    path("buscar.json", views.guest_search_json, name="guest_search_json"),
    path("nuevo/", views.guest_create, name="guest_create"),
    path("<int:pk>/", views.guest_detail, name="guest_detail"),
    path("<int:pk>/editar/", views.guest_edit, name="guest_edit"),
    path("<int:pk>/fusionar/", views.guest_merge, name="guest_merge"),
    path("<int:pk>/anonimizar/", views.guest_anonymize, name="guest_anonymize"),
    path("<int:pk>/fidelidad/", views.guest_loyalty, name="guest_loyalty"),
    *views.company_crud.urls("empresas", "company"),
    *views.tier_crud.urls("niveles-fidelidad", "tier"),
]
