import re
from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from allauth.core.context import request_context
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.password_validation import validate_password
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.adapters import CustomAccountAdapter, CustomSocialAccountAdapter

User = get_user_model()


@pytest.fixture
def google_social_app(db):
    app, _ = SocialApp.objects.get_or_create(
        provider="google",
        name="Google",
        defaults={
            "client_id": "test-client-id.apps.googleusercontent.com",
            "secret": "test-client-secret",
        },
    )
    return app


@pytest.fixture
def mock_google_login_factory(google_social_app):
    def _create_social_login(
        email="newstudent@gmail.com",
        verified=True,
        given_name="Alex",
        family_name="Rana",
        uid="1234567890",
    ):
        user = User(email=email)
        account = SocialAccount(
            provider="google",
            uid=uid,
            extra_data={
                "id": uid,
                "email": email,
                "email_verified": verified,
                "given_name": given_name,
                "family_name": family_name,
                "name": f"{given_name} {family_name}",
            },
        )
        adapter = CustomSocialAccountAdapter()
        provider = adapter.get_provider(request=None, provider="google")
        provider.app = google_social_app
        sociallogin = SocialLogin(
            user=user,
            account=account,
            provider=provider,
            email_addresses=[EmailAddress(email=email, verified=verified, primary=True)],
        )
        return sociallogin

    return _create_social_login


@pytest.mark.django_db
class TestGoogleAuthenticationFlow:
    def test_brand_new_google_signup_creates_student(self, rf, mock_google_login_factory):
        sociallogin = mock_google_login_factory(
            email="freshstudent@example.com",
            verified=True,
            given_name="Fresh",
            family_name="Student",
        )
        request = rf.get("/accounts/google/login/callback/")
        request.session = {}

        adapter = CustomSocialAccountAdapter()
        assert adapter.is_open_for_signup(request, sociallogin) is True

        adapter.pre_social_login(request, sociallogin)
        user = adapter.populate_user(
            request, sociallogin, {"first_name": "Fresh", "last_name": "Student"}
        )

        assert user.role == User.Role.STUDENT
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.first_name == "Fresh"
        assert user.last_name == "Student"

    def test_unverified_email_rejected(self, rf, mock_google_login_factory):
        sociallogin = mock_google_login_factory(
            email="unverified@example.com",
            verified=False,
        )
        request = rf.get("/accounts/google/login/callback/")
        request.session = {}

        adapter = CustomSocialAccountAdapter()
        with pytest.raises(ImmediateHttpResponse) as excinfo:
            adapter.pre_social_login(request, sociallogin)

        assert excinfo.value.response.status_code == 400

    def test_existing_user_linked_by_verified_email(
        self, rf, user_factory, mock_google_login_factory
    ):
        from importlib import import_module

        from django.conf import settings
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.messages.storage.fallback import FallbackStorage

        # Existing user created via admin or seed command
        existing_user = user_factory(
            email="existing@example.com",
            role=User.Role.STUDENT,
        )
        sociallogin = mock_google_login_factory(
            email="existing@example.com",
            verified=True,
            uid="google-uid-existing-123",
        )

        from allauth.core.context import request_context

        # Complete social login flow
        request = rf.post("/accounts/google/login/callback/")
        engine = import_module(settings.SESSION_ENGINE)
        request.session = engine.SessionStore()
        request.user = AnonymousUser()
        request._messages = FallbackStorage(request)

        with request_context(request):
            complete_social_login(request, sociallogin)

        # Should link to existing user without creating a new user or throwing duplicate error
        assert User.objects.filter(email="existing@example.com").count() == 1
        assert SocialAccount.objects.filter(
            uid="google-uid-existing-123", user=existing_user
        ).exists()

    def test_google_login_never_elevates_to_teacher(self, rf, mock_google_login_factory):
        sociallogin = mock_google_login_factory(
            email="attacker@example.com",
            verified=True,
        )
        request = rf.get("/accounts/google/login/callback/")
        adapter = CustomSocialAccountAdapter()
        user = adapter.populate_user(request, sociallogin, {})
        assert user.role == User.Role.STUDENT
        assert user.is_staff is False


@pytest.mark.django_db
class TestRedirectsAndPermissions:
    def test_student_redirected_to_student_dashboard(self, rf, user_factory):
        student = user_factory(role=User.Role.STUDENT)
        request = rf.get("/accounts/login/")
        request.user = student

        adapter = CustomAccountAdapter()
        redirect_url = adapter.get_login_redirect_url(request)
        assert redirect_url == reverse("dashboard:student")

    def test_teacher_redirected_to_teacher_dashboard(self, rf, user_factory):
        teacher = user_factory(email="teacher1@example.com", role=User.Role.TEACHER, is_staff=True)
        request = rf.get("/accounts/login/")
        request.user = teacher

        adapter = CustomAccountAdapter()
        redirect_url = adapter.get_login_redirect_url(request)
        assert redirect_url == reverse("dashboard:teacher")

    def test_safe_next_parameter_redirect(self, rf, user_factory):
        student = user_factory()
        request = rf.get("/accounts/login/?next=/privacy/")
        request.user = student

        adapter = CustomAccountAdapter()
        redirect_url = adapter.get_login_redirect_url(request)
        assert redirect_url == "/privacy/"

    def test_open_redirect_next_parameter_rejected(self, rf, user_factory):
        student = user_factory()
        request = rf.get("/accounts/login/?next=https://malicious-site.com/steal-creds")
        request.user = student

        adapter = CustomAccountAdapter()
        redirect_url = adapter.get_login_redirect_url(request)
        assert redirect_url == reverse("dashboard:student")

    def test_teacher_dashboard_permission_denied_for_students(self, client, user_factory):
        student = user_factory(role=User.Role.STUDENT)
        client.force_login(student)
        response = client.get(reverse("dashboard:teacher"))
        assert response.status_code == 403

    def test_teacher_dashboard_accessible_for_teachers(self, client, user_factory):
        teacher = user_factory(email="teach@example.com", role=User.Role.TEACHER, is_staff=True)
        client.force_login(teacher)
        response = client.get(reverse("dashboard:teacher"))
        assert response.status_code == 200

    def test_unauthenticated_user_redirected_from_dashboard(self, client):
        response = client.get(reverse("dashboard:student"))
        assert response.status_code == 302
        assert reverse("account_login") in response.url


@pytest.mark.django_db
class TestLogoutAndCommands:
    def test_post_logout_clears_session_and_redirects(self, client, user_factory):
        student = user_factory()
        client.force_login(student)
        response = client.post(reverse("account_logout"))
        assert response.status_code == 302
        assert response.url == reverse("core:home")

        # Verify session is logged out
        resp_check = client.get(reverse("dashboard:student"))
        assert resp_check.status_code == 302

    def test_promote_teacher_command(self):
        call_command("promote_teacher", "promoted@example.com")
        user = User.objects.get(email="promoted@example.com")
        assert user.role == User.Role.TEACHER
        assert user.is_staff is True
        assert user.has_usable_password() is False

        # Promoting existing student
        call_command("promote_teacher", "promoted@example.com")
        assert User.objects.filter(email="promoted@example.com").count() == 1


@pytest.mark.django_db
class TestStaticPages:
    def test_privacy_page_returns_200(self, client):
        response = client.get(reverse("core:privacy"))
        assert response.status_code == 200
        assert "Privacy Policy" in response.content.decode("utf-8")

    def test_terms_page_returns_200(self, client):
        response = client.get(reverse("core:terms"))
        assert response.status_code == 200
        assert "Terms of Service" in response.content.decode("utf-8")


@pytest.mark.django_db
class TestGoogleAuthMissingCredentials:
    def test_login_page_renders_friendly_notice_when_google_credentials_missing(
        self, client, settings
    ):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_CLIENT_SECRET = ""
        settings.SOCIALACCOUNT_PROVIDERS = {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
                "APPS": [],
            }
        }
        resp = client.get(reverse("account_login"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Google Sign-In Unavailable" in content
        assert "Authentication credentials have not been configured" in content
        assert "Continue with Google" not in content

    def test_login_page_renders_button_when_google_credentials_present(self, client, settings):
        settings.GOOGLE_CLIENT_ID = "valid-google-id"
        settings.GOOGLE_CLIENT_SECRET = "valid-google-secret"
        settings.SOCIALACCOUNT_PROVIDERS = {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
                "APPS": [
                    {
                        "client_id": "valid-google-id",
                        "secret": "valid-google-secret",
                        "key": "",
                    }
                ],
            }
        }
        resp = client.get(reverse("account_login"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Continue with Google" in content
        assert "Google Sign-In Unavailable" not in content

    def test_oauth_initiation_redirects_when_credentials_missing(self, client, settings):
        settings.GOOGLE_CLIENT_ID = ""
        settings.GOOGLE_CLIENT_SECRET = ""
        settings.SOCIALACCOUNT_PROVIDERS = {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
                "APPS": [],
            }
        }
        resp = client.post(reverse("google_login"))
        assert resp.status_code == 302
        assert resp.url == reverse("account_login")

    def test_real_post_to_google_login_redirects_to_accounts_google_com(self, client, settings):
        """
        Real POST (with CSRF) to /accounts/google/login/ with credentials configured
        asserts a 302 redirect to accounts.google.com with the correct client_id and redirect_uri.
        No mocking of the view itself.
        """
        settings.GOOGLE_CLIENT_ID = "test-real-client-id.apps.googleusercontent.com"
        settings.GOOGLE_CLIENT_SECRET = "test-real-client-secret"
        settings.SOCIALACCOUNT_PROVIDERS = {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
                "APPS": [
                    {
                        "client_id": "test-real-client-id.apps.googleusercontent.com",
                        "secret": "test-real-client-secret",
                        "key": "",
                    }
                ],
            }
        }
        # First GET login page to obtain a real CSRF cookie
        login_resp = client.get(reverse("account_login"), HTTP_HOST="127.0.0.1:8000")
        assert login_resp.status_code == 200
        csrf_token = login_resp.cookies["csrftoken"].value

        # Real POST with CSRF
        resp = client.post(
            reverse("google_login"),
            {"csrfmiddlewaretoken": csrf_token},
            HTTP_HOST="127.0.0.1:8000",
        )
        assert resp.status_code == 302
        location = resp["Location"]
        assert location.startswith("https://accounts.google.com/")
        assert "client_id=test-real-client-id.apps.googleusercontent.com" in location
        assert (
            "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Faccounts%2Fgoogle%2Flogin%2Fcallback%2F"
            in location
        )

    def test_rapid_google_login_posts_trigger_rate_limit_429(self, client, settings):
        """
        Assert that the 31st rapid POST request from the same IP returns HTTP 429 Too Many Requests.
        """
        settings.GOOGLE_CLIENT_ID = "test-real-client-id.apps.googleusercontent.com"
        settings.GOOGLE_CLIENT_SECRET = "test-real-client-secret"
        settings.SOCIALACCOUNT_PROVIDERS = {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
                "APPS": [
                    {
                        "client_id": "test-real-client-id.apps.googleusercontent.com",
                        "secret": "test-real-client-secret",
                        "key": "",
                    }
                ],
            }
        }
        login_resp = client.get(reverse("account_login"), HTTP_HOST="127.0.0.1:8000")
        csrf_token = login_resp.cookies["csrftoken"].value

        # First 30 rapid POST requests succeed with 302
        for _ in range(30):
            r = client.post(
                reverse("google_login"),
                {"csrfmiddlewaretoken": csrf_token},
                HTTP_HOST="127.0.0.1:8000",
            )
            assert r.status_code == 302

        # 31st request exceeds rate limit (30/m) and returns 429
        r_31 = client.post(
            reverse("google_login"),
            {"csrfmiddlewaretoken": csrf_token},
            HTTP_HOST="127.0.0.1:8000",
        )
        assert r_31.status_code == 429
        assert "Too Many Requests" in r_31.content.decode("utf-8")

    def test_callback_url_works_and_not_rate_limited_tightly(self, client, settings):
        """
        Check that /accounts/google/login/callback/ resolves and does not trigger the 30/m initiation limit.
        """
        settings.GOOGLE_CLIENT_ID = "test-real-client-id.apps.googleusercontent.com"
        settings.GOOGLE_CLIENT_SECRET = "test-real-client-secret"
        settings.SOCIALACCOUNT_PROVIDERS = {
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
                "APPS": [
                    {
                        "client_id": "test-real-client-id.apps.googleusercontent.com",
                        "secret": "test-real-client-secret",
                        "key": "",
                    }
                ],
            }
        }
        callback_url = reverse("google_callback")
        # Direct GET without code/state returns allauth authentication error response, NOT 429
        for _ in range(5):
            resp = client.get(callback_url, HTTP_HOST="127.0.0.1:8000")
            assert resp.status_code != 429

    def test_google_oauth_dependencies_available(self):
        """
        Verify that jwt (PyJWT) and cryptography dependencies required by allauth's Google provider
        are installed and importable so missing dependencies fail in CI instead of at login callback.
        """
        import cryptography
        import jwt

        assert hasattr(jwt, "decode")
        assert hasattr(cryptography, "__version__")


@pytest.mark.django_db
class TestPreHijackingMitigation:
    def test_pre_hijacking_unverified_password_invalidated_by_google_login(
        self, rf, mock_google_login_factory, client
    ):
        """
        Pre-hijacking scenario:
        1. An attacker creates an unverified account with a password for victim@example.com.
        2. Later, the real owner performs a Google login with a verified email for victim@example.com.
        Result:
        - The account is linked to the real Google owner.
        - The attacker's earlier password is made unusable.
        - The attacker can no longer log in using their password.
        - The EmailAddress is marked verified.
        """
        # 1. Attacker signs up with a password for victim@example.com
        victim = User.objects.create_user(
            email="victim@example.com",
            password="AttackerPassword123!",
            first_name="Victim",
            last_name="Target",
        )
        EmailAddress.objects.create(
            user=victim,
            email="victim@example.com",
            verified=False,
            primary=True,
        )
        assert victim.has_usable_password() is True
        assert victim.check_password("AttackerPassword123!") is True
        assert EmailAddress.objects.filter(user=victim, verified=True).exists() is False

        # 2. Legitimate Google login by real owner with verified email
        sociallogin = mock_google_login_factory(
            email="victim@example.com",
            verified=True,
            uid="google-victim-real-uid",
            given_name="Victim",
            family_name="Target",
        )

        request = rf.post("/accounts/google/login/callback/")
        request.session = SessionStore()
        request.user = AnonymousUser()
        request._messages = FallbackStorage(request)

        with request_context(request):
            complete_social_login(request, sociallogin)

        # 3. Assert account ownership transferred to Google and password invalidated
        victim.refresh_from_db()
        assert victim.has_usable_password() is False
        assert victim.check_password("AttackerPassword123!") is False
        assert EmailAddress.objects.get(user=victim, email="victim@example.com").verified is True
        assert SocialAccount.objects.filter(
            user=victim, provider="google", uid="google-victim-real-uid"
        ).exists()

        # 4. Attacker attempts to log in via password form and is rejected
        login_resp = client.post(
            reverse("account_login"),
            {"login": "victim@example.com", "password": "AttackerPassword123!"},
        )
        assert login_resp.status_code == 200
        # Check that user is not authenticated in session
        assert "_auth_user_id" not in client.session


@pytest.mark.django_db
class TestVerifiedEmailAddressProvisioningAndTeacherFlows:
    def test_promote_teacher_has_verified_email_and_can_reset_password_and_link_google(
        self, client, rf, mock_google_login_factory
    ):
        """
        Accounts created via promote_teacher receive a verified EmailAddress row.
        The teacher can set a password via 'Forgot password' and can log in via Google.
        """
        teacher_email = "myteacher@example.com"
        call_command("promote_teacher", teacher_email)
        teacher = User.objects.get(email=teacher_email)

        assert teacher.role == User.Role.TEACHER
        assert teacher.is_staff is True
        assert (
            EmailAddress.objects.filter(
                user=teacher, email=teacher_email, verified=True, primary=True
            ).exists()
            is True
        )

        # Teacher requests password reset via "Forgot password"
        mail.outbox.clear()
        reset_req = client.post(
            reverse("account_reset_password"),
            {"email": teacher_email},
        )
        assert reset_req.status_code == 302
        assert len(mail.outbox) == 1
        reset_email = mail.outbox[0]
        assert "Reset Your Password" in reset_email.subject

        # Follow reset link from email
        link_match = re.search(
            r"http://testserver(/accounts/password/reset/key/[^/\s]+/)",
            reset_email.body,
        )
        assert link_match is not None
        key_url = link_match.group(1)

        # Visiting the key URL redirects to set-password form while preserving session token
        key_resp = client.get(key_url, follow=True)
        assert key_resp.status_code == 200
        set_pwd_url = key_resp.redirect_chain[0][0]

        # Submit new password
        post_resp = client.post(
            set_pwd_url,
            {
                "password1": "NewTeacherSecurePass123!",
                "password2": "NewTeacherSecurePass123!",
            },
            follow=True,
        )
        assert post_resp.status_code == 200
        teacher.refresh_from_db()
        assert teacher.check_password("NewTeacherSecurePass123!") is True

        # Teacher logs in with newly set password and lands on teacher dashboard
        login_resp = client.post(
            reverse("account_login"),
            {"login": teacher_email, "password": "NewTeacherSecurePass123!"},
            follow=True,
        )
        assert login_resp.status_code == 200
        assert reverse("dashboard:teacher") in [step[0] for step in login_resp.redirect_chain]

        # Google linking also works for this teacher account without lowering privileges
        sociallogin = mock_google_login_factory(
            email=teacher_email,
            verified=True,
            uid="google-teacher-uid",
            given_name="My",
            family_name="Teacher",
        )
        request = rf.post("/accounts/google/login/callback/")
        request.session = SessionStore()
        request.user = AnonymousUser()
        request._messages = FallbackStorage(request)

        with request_context(request):
            complete_social_login(request, sociallogin)

        teacher.refresh_from_db()
        assert teacher.role == User.Role.TEACHER
        assert teacher.is_staff is True
        assert SocialAccount.objects.filter(
            user=teacher, provider="google", uid="google-teacher-uid"
        ).exists()

    def test_createsuperuser_has_verified_email(self):
        admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="AdminSuperPassword123!",
        )
        assert admin_user.is_staff is True
        assert admin_user.is_superuser is True
        assert (
            EmailAddress.objects.filter(
                user=admin_user, email="admin@example.com", verified=True
            ).exists()
            is True
        )

    def test_seed_demo_provisions_verified_emails(self, settings):
        settings.DEBUG = True
        call_command("seed_demo")
        for email in [
            "teacher@example.com",
            "student1@example.com",
            "student2@example.com",
        ]:
            u = User.objects.get(email=email)
            assert EmailAddress.objects.filter(user=u, email=email, verified=True).exists()


@pytest.mark.django_db
class TestSignupAndResetAbuseDefenses:
    def test_signup_honeypot_rejects_bots(self, client):
        client.get(reverse("account_signup"))
        response = client.post(
            reverse("account_signup"),
            {
                "email": "spambot@example.com",
                "first_name": "Spam",
                "last_name": "Bot",
                "password1": "SpamBotPassword123!",
                "password2": "SpamBotPassword123!",
                "terms": True,
                "website": "https://spam-link.com",
            },
        )
        assert response.status_code == 200
        assert User.objects.filter(email="spambot@example.com").exists() is False

    def test_signup_extra_post_fields_ignored(self, client):
        response = client.post(
            reverse("account_signup"),
            {
                "email": "hacker@example.com",
                "first_name": "Hacker",
                "last_name": "User",
                "password1": "HackerPassword123!",
                "password2": "HackerPassword123!",
                "terms": True,
                "website": "",
                "role": User.Role.TEACHER,
                "is_staff": True,
                "is_superuser": True,
            },
            follow=True,
        )
        assert response.status_code == 200
        user = User.objects.get(email="hacker@example.com")
        assert user.role == User.Role.STUDENT
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_admin_login_rate_limited(self, client):
        cache.clear()
        for _ in range(20):
            r = client.get(reverse("admin_login"), HTTP_HOST="127.0.0.1:8000")
            assert r.status_code != 429

        r_blocked = client.get(reverse("admin_login"), HTTP_HOST="127.0.0.1:8000")
        assert r_blocked.status_code == 429
        assert "Too Many Requests" in r_blocked.content.decode("utf-8")

    def test_password_validators_min_length_and_passphrase(self):
        # Shorter than 10 chars fails
        with pytest.raises(ValidationError) as exc:
            validate_password("Short9!")
        assert "at least 10 characters" in str(exc.value)

        # 10+ characters passphrase without composition rules passes
        validate_password("correct horse battery staple")


@pytest.mark.django_db
class TestAntiEnumerationAndEmailFlows:
    def test_duplicate_signup_sends_account_already_exists_email_via_locmem(self, client, settings):
        assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
        existing = User.objects.create_user(
            email="existingstudent@example.com",
            password="ExistingPassword123!",
            first_name="Existing",
            last_name="Student",
        )
        EmailAddress.objects.create(
            user=existing,
            email="existingstudent@example.com",
            verified=True,
            primary=True,
        )

        mail.outbox.clear()
        # Attempt duplicate signup
        resp = client.post(
            reverse("account_signup"),
            {
                "email": "existingstudent@example.com",
                "first_name": "Someone",
                "last_name": "Else",
                "password1": "DifferentPassword123!",
                "password2": "DifferentPassword123!",
                "terms": True,
                "website": "",
            },
            follow=True,
        )
        # Anti-enumeration redirects to verification sent notice
        assert resp.status_code == 200
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == ["existingstudent@example.com"]
        assert "Account Registration Attempt" in email.subject
        assert "an account with this email address already exists" in email.body

    def test_password_reset_anti_enumeration(self, client):
        mail.outbox.clear()
        resp = client.post(
            reverse("account_reset_password"),
            {"email": "nonexistent_email_404@example.com"},
            follow=True,
        )
        assert resp.status_code == 200
        # Anti-enumeration sends an Unknown Account notice to prevent web user enumeration
        assert len(mail.outbox) == 1
        assert "Unknown Account" in mail.outbox[0].subject
        assert "nonexistent_email_404@example.com" in mail.outbox[0].body


@pytest.mark.django_db
class TestStudentRegistrationAndVerification:
    def test_student_signup_sets_terms_accepted_at_and_requires_verification(self, client):
        mail.outbox.clear()
        resp = client.post(
            reverse("account_signup"),
            {
                "email": "newstudent@example.com",
                "first_name": "Student",
                "last_name": "Learner",
                "password1": "StudentPassword123!",
                "password2": "StudentPassword123!",
                "terms": True,
                "website": "",
            },
            follow=True,
        )
        assert resp.status_code == 200
        user = User.objects.get(email="newstudent@example.com")
        assert user.terms_accepted_at is not None
        assert timezone.now() - user.terms_accepted_at < timedelta(minutes=1)

        # Unverified user cannot log in
        unverified_login = client.post(
            reverse("account_login"),
            {"login": "newstudent@example.com", "password": "StudentPassword123!"},
            follow=True,
        )
        assert "/accounts/confirm-email/" in [step[0] for step in unverified_login.redirect_chain]
        assert "_auth_user_id" not in client.session

        # Follow email verification link (allauth sends confirmation on signup and resends on unverified login)
        assert len(mail.outbox) >= 1
        confirm_match = re.search(
            r"http://testserver(/accounts/confirm-email/[^/\s]+/)",
            mail.outbox[-1].body,
        )
        assert confirm_match is not None
        confirm_url = confirm_match.group(1)

        confirm_resp = client.post(confirm_url, follow=True)
        assert confirm_resp.status_code == 200
        assert EmailAddress.objects.get(user=user, email="newstudent@example.com").verified is True

        # Now student can log in and lands on student dashboard
        login_resp = client.post(
            reverse("account_login"),
            {"login": "newstudent@example.com", "password": "StudentPassword123!"},
            follow=True,
        )
        assert login_resp.status_code == 200
        assert reverse("dashboard:student") in [step[0] for step in login_resp.redirect_chain]

    def test_unicode_nepali_names_save_and_display(self, client):
        resp = client.post(
            reverse("account_signup"),
            {
                "email": "nepali_user@example.com",
                "first_name": "राम",
                "last_name": "बहादुर",
                "password1": "NepaliPassword123!",
                "password2": "NepaliPassword123!",
                "terms": True,
                "website": "",
            },
            follow=True,
        )
        assert resp.status_code == 200
        user = User.objects.get(email="nepali_user@example.com")
        assert user.first_name == "राम"
        assert user.last_name == "बहादुर"
        assert user.get_full_name() == "राम बहादुर"

        # Check template rendering of Unicode name
        client.force_login(user)
        dashboard_resp = client.get(reverse("dashboard:student"))
        assert dashboard_resp.status_code == 200
        assert "राम" in dashboard_resp.content.decode("utf-8")


@pytest.mark.django_db
class TestPasswordChangeSessionHandling:
    def test_account_logout_on_password_change(self, client):
        user = User.objects.create_user(
            email="sessionuser@example.com",
            password="OriginalPassword123!",
        )
        EmailAddress.objects.create(
            user=user,
            email="sessionuser@example.com",
            verified=True,
            primary=True,
        )

        # Log in
        client.post(
            reverse("account_login"),
            {"login": "sessionuser@example.com", "password": "OriginalPassword123!"},
        )
        assert "_auth_user_id" in client.session

        # Change password
        change_resp = client.post(
            reverse("account_change_password"),
            {
                "oldpassword": "OriginalPassword123!",
                "password1": "ReplacementPassword123!",
                "password2": "ReplacementPassword123!",
            },
        )
        assert change_resp.status_code == 302

        # ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True terminates the session
        dash_resp = client.get(reverse("dashboard:student"))
        assert dash_resp.status_code == 302
        assert reverse("account_login") in dash_resp.url
