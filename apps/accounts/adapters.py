import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.base import AuthError
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _

from apps.accounts.permissions import is_teacher_user
from apps.core.utils import get_client_ip as resolve_trusted_client_ip

User = get_user_model()
logger = logging.getLogger(__name__)


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Custom account adapter enabling local password signups for students,
    enforcing role safety, and directing users to role-specific dashboard views.
    """

    def get_client_ip(self, request) -> str:
        """
        Ensure allauth rate limits and security logs use the exact same trusted-proxy
        client IP resolution (with safe REMOTE_ADDR fallback) as our project views.
        """
        return resolve_trusted_client_ip(None, request)

    def is_open_for_signup(self, request) -> bool:
        # Standard email/password signup is open for students
        return True

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        # Ensure signups are always assigned the student role with no staff privileges
        user.role = User.Role.STUDENT
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user

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
        if is_teacher_user(user):
            return reverse("dashboard:teacher")

        return reverse("dashboard:student")

    def respond_user_inactive(self, request, user):
        messages.error(
            request,
            _("This account is currently inactive. Please contact the teacher for assistance."),
        )
        return redirect("account_login")


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom social account adapter ensuring only verified Google accounts can login,
    guaranteeing student role defaults, preventing privilege escalation, and
    mitigating pre-hijacking by invalidating passwords on unverified accounts.
    """

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None,
    ):
        super().on_authentication_error(
            request,
            provider,
            error=error,
            exception=exception,
            extra_context=extra_context,
        )
        if error == AuthError.CANCELLED:
            raise ImmediateHttpResponse(
                render(request, "socialaccount/login_cancelled.html", status=200)
            )

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

        # Pre-hijacking mitigation:
        # If an unverified account already exists (e.g., an attacker signed up with victim's email),
        # upon legitimate verified Google login, transfer ownership: make the unverified password
        # unusable and mark the EmailAddress verified so only the real Google owner has access.
        user = sociallogin.user if (sociallogin.user and sociallogin.user.pk) else None
        if not user:
            emails = [e.email for e in sociallogin.email_addresses if e.verified]
            for email in emails:
                found_user = User.objects.filter(email__iexact=email).first()
                if found_user:
                    user = found_user
                    sociallogin.user = found_user
                    break

        if user and user.pk:
            from allauth.account.models import EmailAddress

            has_verified_email = EmailAddress.objects.filter(
                user=user,
                email__iexact=user.email,
                verified=True,
            ).exists()

            if not has_verified_email:
                logger.info(
                    "Mitigating pre-hijacking for user %s: invalidating previous password on verified Google login",
                    user.email,
                )
                user.set_unusable_password()
                user.save(update_fields=["password"])
                email_obj, _ = EmailAddress.objects.get_or_create(
                    user=user,
                    email=user.email.lower(),
                    defaults={"verified": True, "primary": True},
                )
                if not email_obj.verified:
                    email_obj.verified = True
                    email_obj.primary = True
                    email_obj.save(update_fields=["verified", "primary"])

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
