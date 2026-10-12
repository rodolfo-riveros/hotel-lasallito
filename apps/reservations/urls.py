from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("", views.reservation_list, name="reservation_list"),
    path("calendario/", views.tape_chart, name="tape_chart"),
    path("calendario/mover/", views.tape_move, name="tape_move"),
    path("nueva/", views.reservation_create, name="reservation_create"),
    path("cotizar/", views.quote_preview, name="quote_preview"),
    path("<int:pk>/", views.reservation_detail, name="reservation_detail"),
    path("<int:pk>/editar/", views.reservation_edit, name="reservation_edit"),
    path("<int:pk>/cancelar/", views.reservation_cancel, name="reservation_cancel"),
    path("<int:pk>/pdf/", views.reservation_pdf, name="reservation_pdf"),
    path("<int:pk>/<slug:action>/", views.reservation_action, name="reservation_action"),
    path("grupos/", views.group_list, name="group_list"),
    path("grupos/nuevo/", views.group_edit, name="group_create"),
    path("grupos/<int:pk>/", views.group_detail, name="group_detail"),
    path("grupos/<int:pk>/editar/", views.group_edit, name="group_edit"),
    *views.waitlist_crud.urls("lista-espera", "waitlist"),
]
