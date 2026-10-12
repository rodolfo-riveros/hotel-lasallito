from django.urls import path

from . import views

app_name = "pos"

urlpatterns = [
    path("", views.outlets, name="outlets"),
    path("punto/<int:pk>/", views.floor, name="floor"),
    path("punto/<int:pk>/abrir/", views.order_open, name="order_open"),
    path("comanda/<int:pk>/", views.order, name="order"),
    path("comanda/<int:pk>/precuenta/", views.precheck, name="precheck"),
    path("comanda/<int:pk>/ticket/", views.ticket, name="ticket"),
    path("comanda/<int:pk>/<slug:action>/", views.order_action, name="order_action"),
    path("cocina/", views.kds, name="kds"),
    path("desayunos/", views.breakfast, name="breakfast"),
    path("carta-digital/<int:pk>/", views.public_menu, name="public_menu"),
    *views.outlet_crud.urls("puntos", "outlet"),
    *views.category_crud.urls("categorias", "category"),
    *views.menu_crud.urls("carta", "menuitem"),
    *views.table_crud.urls("mesas", "table"),
]
