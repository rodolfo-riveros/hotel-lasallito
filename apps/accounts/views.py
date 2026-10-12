from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.models import AuditLog

from .decorators import require_perm
from .forms import ForcedPasswordChangeForm, LoginForm, PropertyAccessFormSet, RoleForm, UserForm
from .middleware import SESSION_PROPERTY_KEY
from .models import Permission, Role, User
from .permissions import ACTIONS, MODULES


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


@require_POST
def switch_property(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    try:
        property_id = int(request.POST.get("property"))
    except (TypeError, ValueError):
        property_id = None
    if property_id and request.user.accessible_properties().filter(pk=property_id).exists():
        request.session[SESSION_PROPERTY_KEY] = property_id
    next_url = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/"
    return redirect(next_url)


def password_change(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    form = ForcedPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        messages.success(request, _("Contraseña actualizada."))
        return redirect("core:dashboard")
    return render(request, "accounts/password_change.html", {"form": form})


# --------------------------------------------------------------------------
# Usuarios
# --------------------------------------------------------------------------

USER_AUDIT_FIELDS = ["username", "first_name", "last_name", "email", "is_active", "default_property"]


def _access_summary(user) -> list[str]:
    return sorted(f"{a.property_id}:{a.role.code}:{a.is_active}" for a in user.property_accesses.all())


@require_perm("accounts.view")
def user_list(request):
    query = request.GET.get("q", "").strip()
    users = User.objects.prefetch_related("property_accesses__role", "property_accesses__property")
    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query)
        )
    template = "accounts/partials/user_rows.html" if request.htmx else "accounts/user_list.html"
    return render(request, template, {"users": users, "q": query})


def _save_user(request, user=None):
    is_new = user is None
    user = user or User()
    before = {} if is_new else audit.snapshot(user, USER_AUDIT_FIELDS)
    before_access = [] if is_new else _access_summary(user)
    form = UserForm(request.POST or None, instance=user)
    formset = PropertyAccessFormSet(request.POST or None, instance=user, prefix="access")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            user = form.save()
            formset.instance = user
            formset.save()
            if is_new:
                audit.log(AuditLog.Action.CREATE, user)
            else:
                audit.log_changes(user, before)
            after_access = _access_summary(user)
            if after_access != before_access:
                audit.log(
                    AuditLog.Action.PERMISSION, user, changes={"accesos": [before_access, after_access]}
                )
        messages.success(request, _("Usuario guardado."))
        return redirect("accounts:user_list")
    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "formset": formset, "object": None if is_new else user},
    )


@require_perm("accounts.create")
def user_create(request):
    return _save_user(request)


@require_perm("accounts.edit")
def user_edit(request, pk):
    return _save_user(request, get_object_or_404(User, pk=pk))


# --------------------------------------------------------------------------
# Roles y matriz de permisos
# --------------------------------------------------------------------------


@require_perm("accounts.view")
def role_list(request):
    roles = Role.objects.annotate(
        n_perms=Count("permissions", distinct=True), n_users=Count("accesses", distinct=True)
    )
    return render(request, "accounts/role_list.html", {"roles": roles})


@require_perm("accounts.view")
def role_edit(request, pk=None):
    role = get_object_or_404(Role, pk=pk) if pk else None
    can_edit = request.user.has_pms_perm(request.property, "accounts.edit" if role else "accounts.create")
    form = RoleForm(request.POST or None, instance=role)
    current = set(role.permission_codes()) if role else set()
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            valid = {p.code: p for p in Permission.objects.all()}
            selected = set(request.POST.getlist("perm")) & set(valid)
            audit_fields = ["code", "name", "max_discount_percent", "approval_limit"]
            with transaction.atomic():
                before = audit.snapshot(role, audit_fields) if role else {}
                saved = form.save()
                saved.permissions.set([valid[c] for c in selected])
                if role is None:
                    audit.log(AuditLog.Action.CREATE, saved, changes={"permisos": sorted(selected)})
                else:
                    audit.log_changes(saved, before)
                    added, removed = sorted(selected - current), sorted(current - selected)
                    if added or removed:
                        audit.log(
                            AuditLog.Action.PERMISSION,
                            saved,
                            changes={"agregados": added, "quitados": removed},
                        )
            messages.success(request, _("Rol guardado."))
            return redirect("accounts:role_list")
        current = set(request.POST.getlist("perm"))
    matrix = [
        {
            "module": m,
            "cells": [
                {
                    "code": f"{m.code}.{a}",
                    "available": a in m.actions,
                    "checked": f"{m.code}.{a}" in current,
                }
                for a, _label in ACTIONS
            ],
        }
        for m in MODULES
    ]
    return render(
        request,
        "accounts/role_form.html",
        {"form": form, "object": role, "matrix": matrix, "actions": ACTIONS, "can_edit": can_edit},
    )
