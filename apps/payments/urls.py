from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("prueba/<uuid:token>/", views.test_checkout, name="test_checkout"),
]
