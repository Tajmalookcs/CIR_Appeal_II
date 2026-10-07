from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("appeals/", include("appeals.urls")),
    path("", include("core.urls")),
]
