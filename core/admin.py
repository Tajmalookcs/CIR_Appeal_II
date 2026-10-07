from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "actor", "action", "model_name", "object_repr", "ip_address"]
    list_filter = ["action", "model_name", "timestamp"]
    search_fields = ["username", "user_full_name", "object_repr", "model_name"]
    date_hierarchy = "timestamp"
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
