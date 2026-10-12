from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("portal/<uuid:token>/", views.home, name="home"),
    path("portal/<uuid:token>/pre-check-in/", views.precheckin, name="precheckin"),
    path("portal/<uuid:token>/pagar/", views.pay, name="pay"),
    path("portal/<uuid:token>/solicitar/", views.service_request, name="request"),
    path("portal/<uuid:token>/cuenta/", views.folio, name="folio"),
    path("portal/<uuid:token>/comprobante/<int:pk>/", views.invoice_pdf, name="invoice_pdf"),
    path("portal/<uuid:token>/encuesta/", views.survey, name="survey"),
    path("libro-de-reclamaciones/<slug:code>/", views.complaint_book, name="complaint_book"),
    path("portal-interno/solicitudes/", views.staff_requests, name="staff_requests"),
    path("portal-interno/encuestas/", views.staff_surveys, name="staff_surveys"),
    path("portal-interno/reclamos/", views.staff_complaints, name="staff_complaints"),
    path("portal-interno/reclamos/<int:pk>/", views.staff_complaints, name="staff_complaint"),
]
