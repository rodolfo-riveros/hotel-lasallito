from django.urls import path

from . import views

app_name = "rates"

urlpatterns = [
    path("", views.calendar, name="calendar"),
    *views.plan_crud.urls("planes", "plan"),
    *views.season_crud.urls("temporadas", "season"),
    *views.price_crud.urls("precios", "price"),
    *views.restriction_crud.urls("restricciones", "restriction"),
    *views.promo_crud.urls("promociones", "promo"),
    *views.policy_crud.urls("politicas", "policy"),
]
