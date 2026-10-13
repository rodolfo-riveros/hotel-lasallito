from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.stock, name="stock"),
    path("movimiento/", views.movement, name="movement"),
    path("kardex/<int:pk>/", views.kardex, name="kardex"),
    path("alertas/", views.alerts, name="alerts"),
    path("inventario-fisico/", views.counts, name="counts"),
    path("inventario-fisico/<int:pk>/", views.count_detail, name="count_detail"),
    path("mermas/<int:pk>/decidir/", views.waste_decide, name="waste_decide"),
    path("recetas/", views.recipes, name="recipes"),
    path("recetas/<int:pk>/", views.recipe_edit, name="recipe_edit"),
    path("valorizacion/", views.valuation, name="valuation"),
    *views.warehouse_crud.urls("almacenes", "warehouse"),
    *views.category_crud.urls("categorias", "category"),
    *views.item_crud.urls("articulos", "item"),
    *views.waste_crud.urls("mermas", "waste"),
]
