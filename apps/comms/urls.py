from django.urls import path

from . import views

app_name = "comms"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("automaticos/", views.automations, name="automations"),
    path("notificaciones/", views.notifications, name="notifications"),
    path("notificaciones/<int:pk>/", views.notification_open, name="notification_open"),
    path("reserva/<int:reservation_pk>/enviar/", views.compose, name="compose"),
    *views.template_crud.urls("plantillas", "template"),
]
