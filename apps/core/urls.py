from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("healthz/", views.health_check_view, name="healthz"),
]
