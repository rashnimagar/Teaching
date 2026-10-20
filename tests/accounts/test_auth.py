import pytest
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialLogin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

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
