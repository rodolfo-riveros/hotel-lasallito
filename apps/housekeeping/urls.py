from django.urls import path

from . import views

app_name = "housekeeping"

urlpatterns = [
    path("", views.board, name="board"),
    path("mis-habitaciones/", views.my_tasks, name="my_tasks"),
    path("tarea/<int:pk>/", views.task_detail, name="task_detail"),
    path("minibar/", views.minibar, name="minibar"),
    path("minibar/cargar/", views.minibar_post, name="minibar_post"),
    path("lenceria/", views.linen, name="linen"),
    *views.lost_crud.urls("objetos-perdidos", "lost"),
    *views.linen_crud.urls("lenceria/tipos", "linentype"),
    *views.minibar_crud.urls("minibar/articulos", "minibaritem"),
]
