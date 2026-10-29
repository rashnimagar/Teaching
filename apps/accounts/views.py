from allauth.account.views import LoginView, SignupView
from allauth.socialaccount.providers.google.views import oauth2_login
from django.conf import settings
from django.contrib import admin, messages
from django.shortcuts import redirect

from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.core.utils import get_client_ip


def _has_google_credentials() -> bool:
    google_apps = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get("google", {}).get("APPS", [])
    return bool(
        getattr(settings, "GOOGLE_CLIENT_ID", "")
        or (google_apps and google_apps[0].get("client_id"))
    )


@ratelimit(key=get_client_ip, rate="60/m", block=True)
class RateLimitedLoginView(LoginView):
    """
    Renders the authentication landing page, rate-limited per IP.
    Passes has_google_credentials flag to prevent crashes when credentials are not configured.
    """

    template_name = "account/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_google_credentials"] = _has_google_credentials()
        return context


@ratelimit(key=get_client_ip, rate="30/m", block=True)
class RateLimitedSignupView(SignupView):
    """
    Renders the student signup page, rate-limited per IP.
    Passes has_google_credentials flag for consistent OAuth option display.
    """

    template_name = "account/signup.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_google_credentials"] = _has_google_credentials()
        return context


@ratelimit(key=get_client_ip, rate="30/m", block=True)
def rate_limited_google_login_view(request):
    """
    Initiates Google OAuth authentication, rate-limited to 30 requests per minute per IP.
    Gracefully redirects with user feedback if Google credentials are not configured.
    Delegates to allauth's oauth2_login view to preserve adapter attachment and state.
    """
    if not _has_google_credentials():
        messages.error(
            request,
            "Google Sign-In is temporarily unavailable because credentials have not been configured.",
        )
        return redirect("account_login")

    return oauth2_login(request)


@ratelimit(key=get_client_ip, rate="20/m", block=True)
def rate_limited_admin_login_view(request, extra_context=None):
    """
    Wraps Django admin login with a strict 20/m IP rate limit to protect against brute force.
    """
    return admin.site.login(request, extra_context=extra_context)
