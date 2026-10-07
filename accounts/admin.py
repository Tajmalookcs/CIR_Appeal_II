from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Designation, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "full_name", "designation", "role", "is_active", "last_login"]
    list_filter = ["role", "designation", "is_active", "is_superuser"]
    search_fields = ["username", "full_name", "designation__name", "email"]

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Office Details", {"fields": ("full_name", "designation", "role", "contact_no")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Office Details", {"fields": ("full_name", "designation", "role", "contact_no")}),
    )


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ["name", "short_name", "order", "is_active", "user_count"]
    list_editable = ["short_name", "order", "is_active"]
    search_fields = ["name", "short_name"]

    @admin.display(description="Users")
    def user_count(self, obj):
        return obj.users.count()
