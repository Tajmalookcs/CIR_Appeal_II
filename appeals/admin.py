from django.contrib import admin

from .models import IncomeTaxAppeal, SalesTaxAppeal, Unit, Zone


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0
    fields = ["name", "code", "order", "is_active"]


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "unit_count", "order", "is_active"]
    list_editable = ["code", "order", "is_active"]
    search_fields = ["name", "code"]
    inlines = [UnitInline]

    @admin.display(description="Units")
    def unit_count(self, obj):
        return obj.units.count()


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["name", "zone", "code", "order", "is_active"]
    list_editable = ["code", "order", "is_active"]
    list_filter = ["zone", "is_active"]
    search_fields = ["name", "code", "zone__name"]


@admin.register(SalesTaxAppeal)
class SalesTaxAppealAdmin(admin.ModelAdmin):
    list_display = [
        "appeal_no", "serial_no", "year", "date_of_institution", "appellant_name", "ntn",
        "zone", "unit", "sales_tax_involved",
        "first_expiry_120", "second_expiry_180", "decision_status", "service_status",
    ]
    list_filter = ["decision_status", "service_status", "zone", "date_of_institution"]
    search_fields = ["serial_no", "ntn", "strn", "appellant_name", "oio_no", "oia_no"]
    date_hierarchy = "date_of_institution"
    readonly_fields = [
        "year", "first_expiry_120", "second_expiry_180",
        "created_by", "created_by_name", "created_at",
        "updated_by", "updated_by_name", "updated_at",
    ]


@admin.register(IncomeTaxAppeal)
class IncomeTaxAppealAdmin(admin.ModelAdmin):
    list_display = [
        "appeal_no", "serial_no", "year", "date_of_institution", "appellant_name", "ntn",
        "tax_year", "zone", "unit", "revenue_involved",
        "first_expiry_120", "second_expiry_180", "decision_status", "service_status",
    ]
    list_filter = ["decision_status", "service_status", "zone", "tax_year"]
    search_fields = ["serial_no", "ntn", "cnic", "appellant_name"]
    date_hierarchy = "date_of_institution"
    readonly_fields = [
        "year", "first_expiry_120", "second_expiry_180",
        "created_by", "created_by_name", "created_at",
        "updated_by", "updated_by_name", "updated_at",
    ]
