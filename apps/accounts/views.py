from allauth.account.views import LoginView
from allauth.socialaccount.providers.google.views import oauth2_login
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from apps.core.utils import get_client_ip


@method_decorator(ratelimit(key=get_client_ip, rate="30/m", block=True), name="dispatch")
class RateLimitedLoginView(LoginView):
    """
    Renders the authentication landing page, rate-limited to 30 requests per minute per IP.
    Passes has_google_credentials flag to prevent crashes when credentials are not configured.
    """

    template_name = "account/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        google_apps = (
            getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get("google", {}).get("APPS", [])
        )
        has_credentials = bool(
            getattr(settings, "GOOGLE_CLIENT_ID", "")
            or (google_apps and google_apps[0].get("client_id"))
        )
        context["has_google_credentials"] = has_credentials
        return context


@ratelimit(key=get_client_ip, rate="30/m", block=True)
def rate_limited_google_login_view(request):
    """
    Initiates Google OAuth authentication, rate-limited to 30 requests per minute per IP.
    Gracefully redirects with user feedback if Google credentials are not configured.
    Delegates to allauth's oauth2_login view to preserve adapter attachment and state.
    """
    google_apps = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get("google", {}).get("APPS", [])
    has_credentials = bool(
        getattr(settings, "GOOGLE_CLIENT_ID", "")
        or (google_apps and google_apps[0].get("client_id"))
    )
    if not has_credentials:
        messages.error(
            request,
            "Google Sign-In is temporarily unavailable because credentials have not been configured.",
        )
        return redirect("account_login")

    return oauth2_login(request)
