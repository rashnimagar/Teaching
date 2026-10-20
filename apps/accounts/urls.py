from django.urls import path

from apps.accounts.views import (
    RateLimitedLoginView,
    RateLimitedSignupView,
    rate_limited_google_login_view,
)

urlpatterns = [
    path("login/", RateLimitedLoginView.as_view(), name="account_login"),
    path("signup/", RateLimitedSignupView.as_view(), name="account_signup"),
    path("google/login/", rate_limited_google_login_view, name="google_login"),
]
