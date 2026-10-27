from django.shortcuts import render
from django_ratelimit.exceptions import Ratelimited


class RatelimitMiddleware:
    """
    Middleware that intercepts Ratelimited exceptions and returns an accessible
    HTTP 429 Too Many Requests response page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Ratelimited):
            return render(request, "429.html", status=429)
        return None


import time
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _


class SecurityHeadersMiddleware:
    """
    Sets hardened security headers across all responses:
    - Permissions-Policy: Disables camera, mic, geolocation, payment; delegates
      fullscreen, autoplay, and picture-in-picture to authorized video providers.
    - Cross-Origin-Opener-Policy: Isolates browsing context (same-origin).
    - Cross-Origin-Resource-Policy: Enforced on private downloads/exports (same-origin).
    """

    PERMISSIONS_POLICY = (
        'camera=(), microphone=(), geolocation=(), payment=(), usb=(), '
        'fullscreen=(self "https://www.youtube-nocookie.com" "https://player.vimeo.com" "https://iframe.mediadelivery.net"), '
        'autoplay=(self "https://www.youtube-nocookie.com" "https://player.vimeo.com" "https://iframe.mediadelivery.net"), '
        'picture-in-picture=(self "https://www.youtube-nocookie.com" "https://player.vimeo.com" "https://iframe.mediadelivery.net")'
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Permissions-Policy
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = self.PERMISSIONS_POLICY

        # Cross-Origin-Opener-Policy
        coop = getattr(settings, "SECURE_CROSS_ORIGIN_OPENER_POLICY", "same-origin")
        if coop and "Cross-Origin-Opener-Policy" not in response:
            response["Cross-Origin-Opener-Policy"] = coop

        # Cross-Origin-Resource-Policy on file attachments, FileResponses, or exports
        cd = response.get("Content-Disposition", "")
        ct = response.get("Content-Type", "")
        if "attachment" in cd or ct == "text/csv" or "application/octet-stream" in ct or isinstance(response, FileResponse):
            response.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        return response


class SessionIdleTimeoutMiddleware:
    """
    Terminates authenticated sessions after a period of user inactivity.
    Configured via settings.SESSION_IDLE_TIMEOUT_SECONDS (0 or unset = disabled).
    All authenticated requests, including video position-save requests, count as activity.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timeout = getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 0)
        if timeout and timeout > 0 and request.user.is_authenticated:
            now_ts = int(time.time())
            last_activity = request.session.get("_last_activity")
            if last_activity and (now_ts - last_activity > timeout):
                logout(request)
                try:
                    messages.info(
                        request,
                        _("Your session timed out due to inactivity. Please log in again."),
                    )
                except Exception:
                    pass
                return redirect(settings.LOGIN_URL)
            request.session["_last_activity"] = now_ts

        return self.get_response(request)
