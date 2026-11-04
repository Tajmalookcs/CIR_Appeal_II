from django.urls import path

from . import views

app_name = "registers"

# <tax> is "sales" or "income"; anything else is a 404.
urlpatterns = [
    path("<str:tax>/stay-applications/", views.stay_register, name="stay_register"),
    path("<str:tax>/stay-applications/report/", views.stay_report, name="stay_report"),
    path("<str:tax>/appeal/<int:appeal_pk>/stay/add/", views.stay_create, name="stay_create"),
    path("<str:tax>/stay/<int:pk>/edit/", views.stay_update, name="stay_update"),
    path("<str:tax>/stay/<int:pk>/delete/", views.stay_delete, name="stay_delete"),
]
