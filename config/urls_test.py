"""
Test-only URL configuration.
Includes all canonical URL patterns from config.urls, plus direct error preview routes
(/403/, /404/, /500/) to allow automated security, styling, and CSP tests to verify
error page responses without exposing these routes in production.
"""

from django.urls import path

from apps.core import views as core_views
from config.urls import urlpatterns as base_urlpatterns

urlpatterns = list(base_urlpatterns) + [
    path("403/", core_views.handler403, name="error_403"),
    path("404/", core_views.handler404, name="error_404"),
    path("500/", core_views.handler500, name="error_500"),
]
