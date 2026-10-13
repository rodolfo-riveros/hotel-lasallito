from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report_index, name="index"),
    path("consolidado/", views.consolidated, name="consolidated"),
    path("<slug:key>/", views.report_view, name="report"),
]
