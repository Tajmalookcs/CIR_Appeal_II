from django.urls import path

from . import holidays, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("audit-log/", views.audit_log, name="audit_log"),
    path("holidays/", holidays.holiday_list, name="holiday_list"),
    path("holidays/add/", holidays.holiday_create, name="holiday_create"),
    path("holidays/<int:pk>/edit/", holidays.holiday_update, name="holiday_update"),
    path("holidays/<int:pk>/confirm/", holidays.holiday_confirm, name="holiday_confirm"),
    path("holidays/<int:pk>/delete/", holidays.holiday_delete, name="holiday_delete"),
]
