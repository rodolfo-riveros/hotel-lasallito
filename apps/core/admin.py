from django.contrib import admin

from .models import AuditLog, Currency, ExchangeRate, Property, TaxRule


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "ruc", "city", "is_active"]

    def get_queryset(self, request):
        return Property.all_objects.all()


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "symbol", "is_active"]


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["date", "currency", "buy", "sell", "source"]
    list_filter = ["currency"]


@admin.register(TaxRule)
class TaxRuleAdmin(admin.ModelAdmin):
    list_display = ["name", "property", "rate", "applies_to", "exempt_for_non_domiciled", "is_active"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Solo lectura: la auditoría es inmutable."""

    list_display = ["timestamp", "username", "action", "object_repr", "ip_address"]
    list_filter = ["action"]
    search_fields = ["username", "object_repr"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
