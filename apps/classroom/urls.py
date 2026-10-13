from django.urls import path

from . import views

app_name = "classroom"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("guia/", views.guide, name="guide"),
    path("escenario/", views.launch, name="launch"),
    path("evento/", views.fire_event, name="event"),
    path("hotel/", views.create_property, name="create_property"),
    path("hotel/<int:pk>/restablecer/", views.reset, name="reset"),
    path("alumno/<int:prop_pk>/<int:user_pk>/", views.student, name="student"),
]
