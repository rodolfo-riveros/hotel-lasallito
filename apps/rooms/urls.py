from django.urls import path

from . import views

app_name = "rooms"

urlpatterns = [
    path("", views.rack, name="rack"),
    path("habitacion/<int:pk>/inventario/", views.room_inventory, name="room_inventory"),
    path("habitacion/<int:pk>/limpieza/", views.set_hk_status, name="set_hk_status"),
    *views.room_type_crud.urls("tipos", "roomtype"),
    *views.room_crud.urls("habitaciones", "room"),
    *views.block_crud.urls("bloqueos", "block"),
]
