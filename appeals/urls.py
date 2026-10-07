from django.urls import path

from . import views

app_name = "appeals"

urlpatterns = [
    # Sales Tax register
    path("sales-tax/", views.sales_tax_list, name="sales_tax_list"),
    path("sales-tax/add/", views.sales_tax_create, name="sales_tax_create"),
    path("sales-tax/export/", views.sales_tax_export, name="sales_tax_export"),
    path("sales-tax/<int:pk>/", views.sales_tax_detail, name="sales_tax_detail"),
    path("sales-tax/<int:pk>/cover/", views.sales_tax_cover, name="sales_tax_cover"),
    path("sales-tax/<int:pk>/call-proof/", views.sales_tax_call_proof,
         name="sales_tax_call_proof"),
    path("sales-tax/<int:pk>/order-sheet/", views.sales_tax_order_sheet,
         name="sales_tax_order_sheet"),
    path("sales-tax/<int:pk>/receiving-slip/", views.sales_tax_receiving_slip,
         name="sales_tax_receiving_slip"),
    path("sales-tax/<int:pk>/hearing-notice/", views.sales_tax_hearing_notice,
         name="sales_tax_hearing_notice"),
    path("sales-tax/<int:pk>/stay-call/", views.sales_tax_stay_call,
         name="sales_tax_stay_call"),
    path("sales-tax/<int:pk>/edit/", views.sales_tax_update, name="sales_tax_update"),
    path("sales-tax/<int:pk>/delete/", views.sales_tax_delete, name="sales_tax_delete"),
    # Income Tax register
    path("income-tax/", views.income_tax_list, name="income_tax_list"),
    path("income-tax/add/", views.income_tax_create, name="income_tax_create"),
    path("income-tax/export/", views.income_tax_export, name="income_tax_export"),
    path("income-tax/<int:pk>/", views.income_tax_detail, name="income_tax_detail"),
    path("income-tax/<int:pk>/cover/", views.income_tax_cover, name="income_tax_cover"),
    path("income-tax/<int:pk>/call-proof/", views.income_tax_call_proof,
         name="income_tax_call_proof"),
    path("income-tax/<int:pk>/order-sheet/", views.income_tax_order_sheet,
         name="income_tax_order_sheet"),
    path("income-tax/<int:pk>/edit/", views.income_tax_update, name="income_tax_update"),
    path("income-tax/<int:pk>/delete/", views.income_tax_delete, name="income_tax_delete"),
    # AJAX
    path("sales-tax/mpr/", views.sales_tax_mpr, name="sales_tax_mpr"),
    path("income-tax/mpr/", views.income_tax_mpr, name="income_tax_mpr"),
    path("mpr/letter/", views.mpr_letter, name="mpr_letter"),
    path("api/units/<int:zone_id>/", views.units_for_zone, name="units_for_zone"),
]
