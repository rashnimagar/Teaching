from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("privacy/", views.privacy_view, name="privacy"),
    path("terms/", views.terms_view, name="terms"),
    path("healthz/", views.health_check_view, name="healthz"),
    path("robots.txt", views.robots_txt_view, name="robots_txt"),
]
