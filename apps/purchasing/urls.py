from django.urls import path

from . import views

app_name = "purchasing"

urlpatterns = [
    path("", views.requisition_list, name="requisition_list"),
    path("requisiciones/nueva/", views.requisition_create, name="requisition_create"),
    path("requisiciones/<int:pk>/", views.requisition_detail, name="requisition_detail"),
    path("requisiciones/<int:pk>/editar/", views.requisition_create, name="requisition_edit"),
    path("ordenes/", views.po_list, name="po_list"),
    path("ordenes/<int:pk>/", views.po_detail, name="po_detail"),
    path("ordenes/<int:pk>/pdf/", views.po_pdf, name="po_pdf"),
    path("cuentas-por-pagar/", views.payables, name="payables"),
    *views.supplier_crud.urls("proveedores", "supplier"),
]
