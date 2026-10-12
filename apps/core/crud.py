"""Pantallas genéricas de catálogo (listar, crear, editar, eliminar).

Cada catálogo se declara con un `Crud` y sus URLs se generan con `crud.urls()`.
Respeta permisos "módulo.acción", filtra por la propiedad activa, registra
auditoría y usa borrado lógico cuando el modelo lo soporta.

    rooms_crud = Crud(
        model=RoomType, module="rooms", form_class=RoomTypeForm,
        columns=[("Código", "code"), ("Nombre", "name")], search=["code", "name"],
    )
    urlpatterns += rooms_crud.urls("tipos", "roomtype")
"""

from dataclasses import dataclass, field
from typing import Any

from django import forms
from django.contrib import messages
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.translation import gettext as _

from apps.accounts.decorators import require_perm

from . import audit
from .models import AuditLog, SoftDeleteModel


def has_field(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


class PropertyFormMixin:
    """Limita los desplegables a registros de la propiedad activa."""

    def __init__(self, *args, property=None, **kwargs):
        self.property = property
        super().__init__(*args, **kwargs)
        if property is None:
            return
        for f in self.fields.values():
            qs = getattr(f, "queryset", None)
            if qs is not None and has_field(qs.model, "property"):
                f.queryset = qs.filter(property=property)
            # En registros nuevos solo se ofrecen opciones activas.
            instance = getattr(self, "instance", None)
            is_new = instance is None or instance.pk is None
            if qs is not None and is_new and has_field(qs.model, "is_active"):
                f.queryset = f.queryset.filter(is_active=True)


class PropertyModelForm(PropertyFormMixin, forms.ModelForm):
    pass


@dataclass
class Crud:
    model: type[models.Model]
    module: str
    form_class: type[forms.ModelForm] | None = None
    columns: list[tuple[str, Any]] = field(default_factory=list)
    search: list[str] = field(default_factory=list)
    title: str = ""
    title_plural: str = ""
    ordering: list[str] | None = None
    select_related: list[str] = field(default_factory=list)
    property_scoped: bool | None = None
    list_template: str = "core/crud_list.html"
    form_template: str = "core/crud_form.html"
    filters: list[str] = field(default_factory=list)  # campos con choices o FK para filtrar
    back_url: str | None = None
    help_text: str = ""
    name: str = ""

    def __post_init__(self):
        opts = self.model._meta
        self.title = self.title or str(opts.verbose_name).capitalize()
        self.title_plural = self.title_plural or str(opts.verbose_name_plural).capitalize()
        if self.property_scoped is None:
            self.property_scoped = has_field(self.model, "property")
        if self.form_class is None:
            exclude = ["property", "created_by", "updated_by", "is_deleted", "deleted_at", "deleted_by"]
            self.form_class = forms.modelform_factory(
                self.model,
                form=PropertyModelForm,
                exclude=[f for f in exclude if has_field(self.model, f)],
            )

    # ------------------------------------------------------------------
    def queryset(self, request):
        qs = self.model._default_manager.all()
        if self.property_scoped:
            qs = qs.filter(property=request.property)
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.ordering:
            qs = qs.order_by(*self.ordering)
        return qs

    def url_name(self, action):
        return f"{self.name}_{action}"

    def _form(self, request, instance):
        kwargs = {"instance": instance, "data": request.POST or None, "files": request.FILES or None}
        if issubclass(self.form_class, PropertyFormMixin):
            kwargs["property"] = request.property
        return self.form_class(**kwargs)

    # ------------------------------------------------------------------
    def list_view(self, request, namespace):
        qs = self.queryset(request)
        q = request.GET.get("q", "").strip()
        if q and self.search:
            cond = Q()
            for f in self.search:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        active_filters = {}
        for f in self.filters:
            value = request.GET.get(f)
            if value not in (None, ""):
                qs = qs.filter(**{f: value})
                active_filters[f] = value
        page = Paginator(qs, 30).get_page(request.GET.get("page"))
        rows = []
        for obj in page:
            cells = []
            for _label, getter in self.columns:
                value = getter(obj) if callable(getter) else _resolve(obj, getter)
                cells.append(value)
            rows.append({"obj": obj, "cells": cells})
        filter_widgets = []
        for f in self.filters:
            model_field = self.model._meta.get_field(f.split("__")[0])
            if model_field.choices:
                options = list(model_field.choices)
            elif model_field.is_relation:
                rel_qs = model_field.related_model._default_manager.all()
                if self.property_scoped and has_field(model_field.related_model, "property"):
                    rel_qs = rel_qs.filter(property=request.property)
                options = [(o.pk, str(o)) for o in rel_qs[:200]]
            else:
                options = [("1", _("Sí")), ("0", _("No"))]
            filter_widgets.append(
                {
                    "name": f,
                    "label": model_field.verbose_name,
                    "options": options,
                    "value": active_filters.get(f, ""),
                }
            )
        perms = request.user.pms_permissions(request.property)
        context = {
            "crud": self,
            "page": page,
            "rows": rows,
            "q": q,
            "filters": filter_widgets,
            "namespace": namespace,
            "can_create": f"{self.module}.create" in perms,
            "can_edit": f"{self.module}.edit" in perms,
            "can_delete": f"{self.module}.void" in perms,
            "create_url": reverse(f"{namespace}:{self.url_name('create')}"),
            "edit_url_name": f"{namespace}:{self.url_name('edit')}",
            "delete_url_name": f"{namespace}:{self.url_name('delete')}",
        }
        return render(request, self.list_template, context)

    def form_view(self, request, namespace, pk=None):
        instance = get_object_or_404(self.queryset(request), pk=pk) if pk else self.model()
        perm = f"{self.module}.edit" if pk else f"{self.module}.create"
        if not request.user.has_pms_perm(request.property, perm):
            raise PermissionDenied
        if not pk and self.property_scoped:
            instance.property = request.property
        form = self._form(request, instance)
        audit_fields = [f for f in form.fields if has_field(self.model, f)]
        before = audit.snapshot(instance, audit_fields) if pk else {}
        if request.method == "POST" and form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                if self.property_scoped and not pk:
                    obj.property = request.property
                obj.save()
                form.save_m2m()
                if pk:
                    audit.log_changes(obj, before)
                else:
                    audit.log(AuditLog.Action.CREATE, obj)
            messages.success(request, _("%(name)s guardado.") % {"name": self.title})
            return redirect(f"{namespace}:{self.url_name('list')}")
        return render(
            request,
            self.form_template,
            {
                "crud": self,
                "form": form,
                "object": instance if pk else None,
                "list_url": reverse(f"{namespace}:{self.url_name('list')}"),
            },
        )

    def delete_view(self, request, namespace, pk):
        if request.method != "POST":
            raise PermissionDenied
        obj = get_object_or_404(self.queryset(request), pk=pk)
        try:
            with transaction.atomic():
                audit.log(AuditLog.Action.DELETE, obj)
                if isinstance(obj, SoftDeleteModel):
                    obj.delete()
                elif has_field(self.model, "is_active"):
                    obj.is_active = False
                    obj.save(update_fields=["is_active"])
                else:
                    obj.delete()
            messages.success(request, _("Registro eliminado."))
        except ProtectedError:
            messages.error(request, _("No se puede eliminar: hay registros que dependen de este."))
        return redirect(f"{namespace}:{self.url_name('list')}")

    # ------------------------------------------------------------------
    def urls(self, prefix: str, name: str) -> list:
        self.name = name
        module = self.module

        @require_perm(f"{module}.view")
        def list_view(request):
            return self.list_view(request, request.resolver_match.namespace)

        @require_perm(f"{module}.view")
        def form_view(request, pk=None):
            return self.form_view(request, request.resolver_match.namespace, pk)

        @require_perm(f"{module}.void")
        def delete_view(request, pk):
            return self.delete_view(request, request.resolver_match.namespace, pk)

        return [
            path(f"{prefix}/", list_view, name=self.url_name("list")),
            path(f"{prefix}/nuevo/", form_view, name=self.url_name("create")),
            path(f"{prefix}/<int:pk>/", form_view, name=self.url_name("edit")),
            path(f"{prefix}/<int:pk>/eliminar/", delete_view, name=self.url_name("delete")),
        ]


def _resolve(obj, attr: str):
    value = obj
    for part in attr.split("."):
        if value is None:
            return None
        display = getattr(value, f"get_{part}_display", None)
        value = display() if callable(display) else getattr(value, part, None)
        if callable(value) and not isinstance(value, models.Model):
            value = value()
    return value
