from datetime import timedelta

import pytest
from allauth.account.adapter import get_adapter
from django.core.checks import run_checks
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.core.utils import get_client_ip, parse_valid_ip
from apps.courses.models import Course, CourseMaterial, Enrollment, MaterialItem


class TestGetClientIpAndTrustedProxy:
    """
    Tests for get_client_ip and CustomAccountAdapter.get_client_ip covering:
    - NUM_PROXIES=0 ignoring spoofed X-Forwarded-For
    - Configured NUM_PROXIES reading the exact right-most N-th hop
    - Attacker prepending fake address to X-Forwarded-For
    - Fallback to REMOTE_ADDR when header has fewer entries than NUM_PROXIES
    - Ignoring malformed entries and falling back to REMOTE_ADDR
    - IPv6 parsing (plain, bracketed, and with port)
    """

    def setup_method(self):
        self.rf = RequestFactory()

    def test_parse_valid_ip_handles_ipv4_ipv6_and_malformed(self):
        assert parse_valid_ip("203.0.113.10") == "203.0.113.10"
        assert parse_valid_ip("203.0.113.10:8080") == "203.0.113.10"
        assert parse_valid_ip("2001:db8::1") == "2001:db8::1"
        assert parse_valid_ip("[2001:db8::1]") == "2001:db8::1"
        assert parse_valid_ip("[2001:db8::1]:443") == "2001:db8::1"
        assert parse_valid_ip("not-an-ip") is None
        assert parse_valid_ip("999.999.999.999") is None
        assert parse_valid_ip("") is None
        assert parse_valid_ip(None) is None

    @override_settings(
        NUM_PROXIES=0,
        ALLAUTH_TRUSTED_PROXY_COUNT=0,
        TRUSTED_CLIENT_IP_HEADER=None,
        ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None,
    )
    def test_no_proxy_ignores_spoofed_xff(self):
        req = self.rf.get(
            reverse("core:home"),
            REMOTE_ADDR="198.51.100.50",
            HTTP_X_FORWARDED_FOR="203.0.113.1, 203.0.113.2",
        )
        assert get_client_ip(None, req) == "198.51.100.50"
        assert get_adapter().get_client_ip(req) == "198.51.100.50"

    @override_settings(
        NUM_PROXIES=2,
        ALLAUTH_TRUSTED_PROXY_COUNT=2,
        TRUSTED_CLIENT_IP_HEADER=None,
        ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None,
    )
    def test_configured_proxies_reads_right_hop_and_ignores_prepended_attacker_ip(self):
        # Attacker prepends 1.2.3.4; real client is 203.0.113.42; edge proxy is 10.0.0.1
        req = self.rf.get(
            reverse("core:home"),
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 192.0.2.99, 203.0.113.42, 10.0.0.1",
        )
        assert get_client_ip(None, req) == "203.0.113.42"
        assert get_adapter().get_client_ip(req) == "203.0.113.42"

    @override_settings(
        NUM_PROXIES=2,
        ALLAUTH_TRUSTED_PROXY_COUNT=2,
        TRUSTED_CLIENT_IP_HEADER=None,
        ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None,
    )
    def test_fewer_entries_than_num_proxies_falls_back_to_remote_addr(self):
        req = self.rf.get(
            reverse("core:home"),
            REMOTE_ADDR="198.51.100.77",
            HTTP_X_FORWARDED_FOR="203.0.113.42",
        )
        assert get_client_ip(None, req) == "198.51.100.77"
        assert get_adapter().get_client_ip(req) == "198.51.100.77"

    @override_settings(
        NUM_PROXIES=1,
        ALLAUTH_TRUSTED_PROXY_COUNT=1,
        TRUSTED_CLIENT_IP_HEADER=None,
        ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None,
    )
    def test_malformed_hop_falls_back_to_remote_addr(self):
        req = self.rf.get(
            reverse("core:home"),
            REMOTE_ADDR="198.51.100.88",
            HTTP_X_FORWARDED_FOR="203.0.113.10, garbage-injected-hop",
        )
        assert get_client_ip(None, req) == "198.51.100.88"
        assert get_adapter().get_client_ip(req) == "198.51.100.88"

    @override_settings(
        NUM_PROXIES=1,
        ALLAUTH_TRUSTED_PROXY_COUNT=1,
        TRUSTED_CLIENT_IP_HEADER=None,
        ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None,
    )
    def test_ipv6_hop_is_extracted_and_normalized(self):
        req = self.rf.get(
            reverse("core:home"),
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.1, [2001:db8:85a3::8a2e:370:7334]:8443",
        )
        assert get_client_ip(None, req) == "2001:db8:85a3::8a2e:370:7334"
        assert get_adapter().get_client_ip(req) == "2001:db8:85a3::8a2e:370:7334"


@pytest.mark.django_db
class TestSpoofedXffRateLimitEnforcement:
    """
    Verify that a spoofed X-Forwarded-For cannot bypass either custom view rate limits
    or django-allauth's ACCOUNT_RATE_LIMITS when NUM_PROXIES=0, and that the configured
    hop count is respected when NUM_PROXIES > 0.
    """

    @override_settings(
        NUM_PROXIES=0,
        ALLAUTH_TRUSTED_PROXY_COUNT=0,
        ACCOUNT_RATE_LIMITS={"reset_password": "2/m/ip"},
    )
    def test_spoofed_xff_cannot_bypass_allauth_rate_limit_when_no_proxy_configured(self, client):
        reset_url = reverse("account_reset_password")
        # Request 1 & 2 from same REMOTE_ADDR with rotating spoofed X-Forwarded-For
        r1 = client.post(
            reset_url,
            {"email": "nobody1@example.com"},
            REMOTE_ADDR="198.51.100.10",
            HTTP_X_FORWARDED_FOR="203.0.113.1",
        )
        assert r1.status_code in (200, 302)

        r2 = client.post(
            reset_url,
            {"email": "nobody2@example.com"},
            REMOTE_ADDR="198.51.100.10",
            HTTP_X_FORWARDED_FOR="203.0.113.2",
        )
        assert r2.status_code in (200, 302)

        # 3rd request from same REMOTE_ADDR with a fresh spoofed XFF must be blocked (429) by allauth
        r3 = client.post(
            reset_url,
            {"email": "nobody3@example.com"},
            REMOTE_ADDR="198.51.100.10",
            HTTP_X_FORWARDED_FOR="203.0.113.3",
        )
        assert r3.status_code == 429

    @override_settings(
        NUM_PROXIES=2,
        ALLAUTH_TRUSTED_PROXY_COUNT=2,
        ACCOUNT_RATE_LIMITS={"reset_password": "2/m/ip"},
    )
    def test_allauth_rate_limit_reads_right_hop_when_proxies_configured(self, client):
        reset_url = reverse("account_reset_password")
        # Real client is 203.0.113.55 (2nd hop from right); attacker rotates prepended 1st hop
        for i in range(2):
            resp = client.post(
                reset_url,
                {"email": f"user{i}@example.com"},
                REMOTE_ADDR="127.0.0.1",
                HTTP_X_FORWARDED_FOR=f"192.0.2.{i + 1}, 203.0.113.55, 10.0.0.1",
            )
            assert resp.status_code in (200, 302)

        # 3rd attempt with a new fake prepended hop still resolves to 203.0.113.55 -> 429
        resp_blocked = client.post(
            reset_url,
            {"email": "user3@example.com"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="192.0.2.250, 203.0.113.55, 10.0.0.1",
        )
        assert resp_blocked.status_code == 429

        # A genuinely different client on the 2nd hop from right (203.0.113.99) is allowed
        resp_other_client = client.post(
            reset_url,
            {"email": "other@example.com"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="192.0.2.1, 203.0.113.99, 10.0.0.1",
        )
        assert resp_other_client.status_code in (200, 302)


@pytest.mark.django_db
class TestEndpointRateLimitBehavior429:
    """
    Behavioral rate-limit tests verifying that exceeding the configured threshold
    returns HTTP 429 Too Many Requests for:
    1. Login (account_login)
    2. Assignment submission (assignments:detail POST)
    3. Material download request (learn:material_request POST)
    4. CSV export (dashboard:teacher_course_grades_export GET)
    """

    @pytest.fixture(autouse=True)
    def setup_fixtures(self, user_factory):
        self.teacher = user_factory(
            email="rl_teacher@example.com",
            role=User.Role.TEACHER,
            is_staff=True,
        )
        self.student = user_factory(
            email="rl_student@example.com",
            role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(
            title="Rate Limit Course",
            slug="rl-course",
            is_published=True,
        )
        Enrollment.objects.create(
            student=self.student,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        self.assignment = Assignment.objects.create(
            course=self.course,
            title="Rate Limit Assignment",
            instructions="Test submission rate limit.",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=7),
            is_published=True,
        )
        self.material = CourseMaterial.objects.create(
            course=self.course,
            title="Rate Limit Material",
            is_published=True,
        )
        self.material_item = MaterialItem.objects.create(
            material=self.material,
            title="Restricted Handout",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            file=SimpleUploadedFile(
                "handout.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"
            ),
            is_published=True,
        )

    @override_settings(NUM_PROXIES=0, ALLAUTH_TRUSTED_PROXY_COUNT=0)
    def test_login_exceeding_rate_limit_returns_429(self, client):
        login_url = reverse("account_login")
        # RateLimitedLoginView has @track_ratelimit(key=get_client_ip, rate="60/m", block=True)
        for _ in range(60):
            resp = client.post(
                login_url,
                {"login": self.student.email, "password": "WrongPassword!"},
                REMOTE_ADDR="198.51.100.200",
            )
            assert resp.status_code == 200

        resp_exceeded = client.post(
            login_url,
            {"login": self.student.email, "password": "WrongPassword!"},
            REMOTE_ADDR="198.51.100.200",
        )
        assert resp_exceeded.status_code == 429

    def test_assignment_submission_exceeding_rate_limit_returns_429(self, client):
        client.force_login(self.student)
        url = reverse(
            "assignments:detail",
            kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
        )
        # Limit is 10/m per user on POST
        for i in range(10):
            resp = client.post(url, {"content_text": f"Attempt {i + 1}"})
            assert resp.status_code in (200, 302)

        resp_exceeded = client.post(url, {"content_text": "Attempt 11"})
        assert resp_exceeded.status_code == 429

    def test_material_download_request_exceeding_rate_limit_returns_429(self, client):
        client.force_login(self.student)
        url = reverse(
            "learn:material_request",
            kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
        )
        # Limit is 15/m per user on POST
        for i in range(15):
            resp = client.post(url, {"request_note": f"Request {i + 1}"})
            assert resp.status_code in (200, 302)

        resp_exceeded = client.post(url, {"request_note": "Request 16"})
        assert resp_exceeded.status_code == 429

    def test_csv_export_exceeding_rate_limit_returns_429(self, client):
        client.force_login(self.teacher)
        url = reverse("dashboard:teacher_course_grades_export", kwargs={"slug": self.course.slug})
        # Limit is 10/m per user on GET
        for _ in range(10):
            resp = client.get(url)
            assert resp.status_code == 200

        resp_exceeded = client.get(url)
        assert resp_exceeded.status_code == 429


class TestProductionSharedCacheDeployCheck:
    """
    Tests for core.E001 deploy check:
    Fails under deploy=True when CACHES['default']['BACKEND'] is LocMemCache or DummyCache,
    and passes when a shared cache (RedisCache or DatabaseCache) is configured.
    """

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "unique-snowflake",
            }
        }
    )
    def test_locmem_cache_fails_deploy_check_with_core_e001(self):
        errors = run_checks(include_deployment_checks=True)
        error_ids = [e.id for e in errors]
        assert "core.E001" in error_ids

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.dummy.DummyCache",
            }
        }
    )
    def test_dummy_cache_fails_deploy_check_with_core_e001(self):
        errors = run_checks(include_deployment_checks=True)
        error_ids = [e.id for e in errors]
        assert "core.E001" in error_ids

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://127.0.0.1:6379/1",
            }
        }
    )
    def test_redis_cache_passes_core_e001(self):
        errors = run_checks(include_deployment_checks=True)
        error_ids = [e.id for e in errors]
        assert "core.E001" not in error_ids

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": "django_cache_table",
            }
        }
    )
    def test_database_cache_passes_core_e001(self):
        errors = run_checks(include_deployment_checks=True)
        error_ids = [e.id for e in errors]
        assert "core.E001" not in error_ids
