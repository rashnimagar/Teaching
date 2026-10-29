from allauth.account import views as allauth_account_views
from allauth.socialaccount.providers.google.views import oauth2_callback
from django.urls import path, re_path

from apps.accounts.views import (
    RateLimitedLoginView,
    RateLimitedSignupView,
    rate_limited_google_login_view,
)

urlpatterns = [
    path("login/", RateLimitedLoginView.as_view(), name="account_login"),
    path("signup/", RateLimitedSignupView.as_view(), name="account_signup"),
    path("logout/", allauth_account_views.logout, name="account_logout"),
    path(
        "password/change/",
        allauth_account_views.password_change,
        name="account_change_password",
    ),
    path(
        "password/reset/",
        allauth_account_views.password_reset,
        name="account_reset_password",
    ),
    path(
        "password/reset/done/",
        allauth_account_views.password_reset_done,
        name="account_reset_password_done",
    ),
    re_path(
        r"^password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
        allauth_account_views.password_reset_from_key,
        name="account_reset_password_from_key",
    ),
    path(
        "password/reset/key/done/",
        allauth_account_views.password_reset_from_key_done,
        name="account_reset_password_from_key_done",
    ),
    path(
        "confirm-email/",
        allauth_account_views.email_verification_sent,
        name="account_email_verification_sent",
    ),
    re_path(
        r"^confirm-email/(?P<key>[-:\w]+)/$",
        allauth_account_views.confirm_email,
        name="account_confirm_email",
    ),
    path("google/login/", rate_limited_google_login_view, name="google_login"),
    path("google/login/callback/", oauth2_callback, name="google_callback"),
]
