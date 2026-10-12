from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Permission, PropertyAccess, Role, User


class PropertyAccessInline(admin.TabularInline):
    model = PropertyAccess
    fk_name = "user"
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [PropertyAccessInline]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("PMS", {"fields": ("phone", "preferred_language", "default_property", "must_change_password")}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_system", "max_discount_percent"]
    filter_horizontal = ["permissions"]


admin.site.register(Permission)
