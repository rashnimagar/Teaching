import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

User = get_user_model()
logger = logging.getLogger(__name__)


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Custom account adapter disabling local password signups for students
    and directing users to role-specific dashboard views upon login.
    """

    def is_open_for_signup(self, request) -> bool:
        # Disable direct email/password signups; students must sign in with Google
        return False

    def get_login_redirect_url(self, request) -> str:
        # Check for a requested 'next' parameter in POST or GET
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return next_url

        # Direct authenticated teachers/staff to teacher dashboard, students to student dashboard
        user = request.user
        if user.is_authenticated and (user.is_teacher or user.is_staff):
            return reverse("dashboard:teacher")

        return reverse("dashboard:student")


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom social account adapter ensuring only verified Google accounts can login,
    guaranteeing student role defaults, and preventing privilege escalation.
    """

    def is_open_for_signup(self, request, sociallogin) -> bool:
        # Allow brand-new Google users to sign up
        return True

    def pre_social_login(self, request, sociallogin):
        super().pre_social_login(request, sociallogin)

        # Enforce that Google has verified the email address
        extra_data = sociallogin.account.extra_data or {}
        email_verified = extra_data.get("email_verified", False)

        # Also check email addresses attached to sociallogin if extra_data doesn't explicitly flag it
        if not email_verified:
            for email_address in sociallogin.email_addresses:
                if email_address.verified:
                    email_verified = True
                    break

        if not email_verified:
            logger.warning(
                "Social login rejected for unverified email: %s",
                sociallogin.account.uid,
            )
            raise ImmediateHttpResponse(
                render(request, "account/unverified_email.html", status=400)
            )

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        # Extract name attributes from Google profile
        extra_data = sociallogin.account.extra_data or {}
        first_name = (
            data.get("first_name")
            or extra_data.get("given_name")
            or extra_data.get("name", "").split(" ")[0]
        )
        last_name = (
            data.get("last_name")
            or extra_data.get("family_name")
            or " ".join(extra_data.get("name", "").split(" ")[1:])
        )

        user.first_name = first_name or ""
        user.last_name = last_name or ""

        # Google login must NEVER grant teacher or staff privileges
        if not user.pk:
            user.role = User.Role.STUDENT
            user.is_staff = False
            user.is_superuser = False

        return user
