from django.urls import path

from . import views

app_name = "channels"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("simular-reserva/", views.simulate_inbound, name="simulate"),
    path("<int:pk>/mapeo/", views.mappings, name="mappings"),
    path("<int:pk>/publicado/", views.published, name="published"),
    *views.channel_crud.urls("canales", "channel"),
]
