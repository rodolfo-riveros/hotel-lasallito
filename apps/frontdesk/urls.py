from django.urls import path

from . import views

app_name = "frontdesk"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("check-in/<int:pk>/", views.check_in, name="check_in"),
    path("check-out/<int:pk>/", views.check_out, name="check_out"),
    path("walk-in/", views.walk_in, name="walk_in"),
    path("cambio-habitacion/<int:pk>/", views.move_room, name="move_room"),
    path("equipaje/", views.luggage, name="luggage"),
    path("novedades/", views.shift_log, name="shift_log"),
    path("despertador/", views.wakeups, name="wakeups"),
    path("cierre-de-dia/", views.night_audit, name="night_audit"),
    path("contingencia/<slug:kind>.<slug:fmt>", views.contingency, name="contingency"),
]
