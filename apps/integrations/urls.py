from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("llaves/<int:pk>/", views.duplicate_key, name="duplicate_key"),
    path("pbx/simular/", views.simulate_call, name="simulate_call"),
    path("pbx/cdr/", views.pbx_webhook, name="pbx_webhook"),
]
