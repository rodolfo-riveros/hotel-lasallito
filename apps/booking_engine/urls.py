from django.urls import path

from . import views

app_name = "booking_engine"

urlpatterns = [
    path("reservar/", views.search, name="search"),
    path("reservar/datos/", views.book, name="book"),
    path("reservar/confirmacion/<uuid:token>/", views.confirmation, name="confirmation"),
    path("reservar/grupos/", views.group_request, name="group"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
    path("motor-web/solicitudes/", views.group_list, name="group_list"),
]
