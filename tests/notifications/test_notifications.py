from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from apps.notifications.context_processors import notifications_context
from apps.notifications.models import Notification, validate_internal_url
from apps.notifications.services import create_notification


@pytest.mark.django_db
class TestNotificationValidation:
    def test_valid_internal_urls_accepted(self):
        valid_urls = [
            "/learn/python-101/materials/",
            "/notifications/",
            "/dashboard/student/",
        ]
        for url in valid_urls:
            validate_internal_url(url)

    def test_urls_with_backslashes_rejected(self):
        with pytest.raises(ValidationError, match="URL must not contain backslashes"):
            validate_internal_url(r"/learn\python/")

    def test_urls_with_newlines_rejected(self):
        with pytest.raises(
            ValidationError, match="URL must not contain control characters or newlines"
        ):
            validate_internal_url("/learn/\npython/")

    def test_urls_with_carriage_returns_rejected(self):
        with pytest.raises(
            ValidationError, match="URL must not contain control characters or newlines"
        ):
            validate_internal_url("/learn/\rpython/")

    def test_urls_with_control_characters_rejected(self):
        with pytest.raises(
            ValidationError, match="URL must not contain control characters or newlines"
        ):
            validate_internal_url("/learn/\x00python/")

    def test_external_scheme_rejected(self):
        with pytest.raises(
            ValidationError, match="URL must be an internal path starting with a single '/'"
        ):
            validate_internal_url("https://malicious.com/phish")

    def test_protocol_relative_url_rejected(self):
        with pytest.raises(
            ValidationError, match="URL must be an internal path starting with a single '/'"
        ):
            validate_internal_url("//malicious.com/phish")

    def test_relative_path_without_leading_slash_rejected(self):
        with pytest.raises(
            ValidationError, match="URL must be an internal path starting with a single '/'"
        ):
            validate_internal_url("learn/materials/")


@pytest.mark.django_db
class TestNotificationServicesAndIsolation:
    def test_notification_creation_and_student_isolation(self, user_factory, client):
        student_a = user_factory(email="student_a@example.com")
        student_b = user_factory(email="student_b@example.com")

        notif_a = create_notification(
            recipient=student_a,
            kind=Notification.Kind.DOWNLOAD_APPROVED,
            title="Download Approved: Lecture 1",
            body="Your request has been approved.",
            url="/learn/test-course/materials/",
        )
        notif_b = create_notification(
            recipient=student_b,
            kind=Notification.Kind.DOWNLOAD_DENIED,
            title="Download Denied: Private Notes",
            body="Your request was denied.",
            url="/learn/test-course/materials/",
        )

        # Student A logs in
        client.force_login(student_a)
        resp_a = client.get(reverse("notifications:list"))
        assert resp_a.status_code == 200
        content_a = resp_a.content.decode("utf-8")
        assert notif_a.title in content_a
        assert notif_b.title not in content_a  # Student B's notif is completely isolated

        # Student B logs in
        client.force_login(student_b)
        resp_b = client.get(reverse("notifications:list"))
        assert resp_b.status_code == 200
        content_b = resp_b.content.decode("utf-8")
        assert notif_b.title in content_b
        assert notif_a.title not in content_b

    def test_mark_single_notification_read(self, user_factory, client):
        student = user_factory(email="student_read@example.com")
        notif = create_notification(
            recipient=student,
            kind=Notification.Kind.DOWNLOAD_APPROVED,
            title="Test Notice",
            body="Notice body",
            url="/notifications/",
        )
        assert not notif.is_read

        client.force_login(student)
        url = reverse("notifications:mark_read", args=[notif.id])
        resp = client.post(url)
        assert resp.status_code == 302

        notif.refresh_from_db()
        assert notif.is_read
        assert notif.read_at is not None

    def test_mark_all_notifications_read(self, user_factory, client):
        student = user_factory(email="student_bulk_read@example.com")
        for i in range(3):
            create_notification(
                recipient=student,
                kind=Notification.Kind.DOWNLOAD_APPROVED,
                title=f"Notice {i}",
                body="Body",
                url="/notifications/",
            )

        assert Notification.objects.filter(recipient=student, read_at__isnull=True).count() == 3

        client.force_login(student)
        resp = client.post(reverse("notifications:mark_all_read"))
        assert resp.status_code == 302

        assert Notification.objects.filter(recipient=student, read_at__isnull=True).count() == 0


@pytest.mark.django_db
class TestNotificationContextProcessor:
    def test_anonymous_user_returns_zero(self, rf):
        from django.contrib.auth.models import AnonymousUser

        request = rf.get("/")
        request.user = AnonymousUser()

        ctx = notifications_context(request)
        assert ctx["unread_notifications_count"] == 0
        assert ctx["unread_notifications_display"] == ""

    def test_unread_count_under_hundred(self, rf, user_factory):
        student = user_factory(email="count_student@example.com")
        for _ in range(5):
            create_notification(
                recipient=student,
                kind=Notification.Kind.DOWNLOAD_APPROVED,
                title="Hello",
                body="World",
                url="/notifications/",
            )

        request = rf.get("/")
        request.user = student
        ctx = notifications_context(request)
        assert ctx["unread_notifications_count"] == 5
        assert ctx["unread_notifications_display"] == "5"

    def test_unread_count_over_99_displays_99_plus(self, rf, user_factory):
        student = user_factory(email="overflow_student@example.com")
        notifications = [
            Notification(
                recipient=student,
                kind=Notification.Kind.DOWNLOAD_APPROVED,
                title=f"Notice {i}",
                body="Bulk",
                url="/notifications/",
            )
            for i in range(105)
        ]
        Notification.objects.bulk_create(notifications)

        request = rf.get("/")
        request.user = student
        ctx = notifications_context(request)
        assert ctx["unread_notifications_count"] == 105
        assert ctx["unread_notifications_display"] == "99+"

    def test_context_processor_survives_database_error(self, rf, user_factory):
        student = user_factory(email="db_error_student@example.com")
        request = rf.get("/")
        request.user = student

        with patch.object(
            Notification.objects, "filter", side_effect=DatabaseError("DB connection lost")
        ):
            ctx = notifications_context(request)
            assert ctx["unread_notifications_count"] == 0
            assert ctx["unread_notifications_display"] == ""


@pytest.mark.django_db
class TestNotificationRetentionAndEmail:
    def test_cleanup_old_read_notifications_command(self, user_factory):
        student = user_factory(email="retention_student@example.com")
        now = timezone.now()

        # Old read notification (>90 days ago)
        old_read = create_notification(
            recipient=student,
            kind=Notification.Kind.DOWNLOAD_APPROVED,
            title="Old Read",
            body="Body",
            url="/notifications/",
        )
        old_read.read_at = now - timedelta(days=95)
        old_read.save()

        # Recent read notification (10 days ago)
        recent_read = create_notification(
            recipient=student,
            kind=Notification.Kind.DOWNLOAD_APPROVED,
            title="Recent Read",
            body="Body",
            url="/notifications/",
        )
        recent_read.read_at = now - timedelta(days=10)
        recent_read.save()

        # Old unread notification (never deleted by read retention!)
        old_unread = create_notification(
            recipient=student,
            kind=Notification.Kind.DOWNLOAD_APPROVED,
            title="Old Unread",
            body="Body",
            url="/notifications/",
        )

        out = StringIO()
        # Dry-run
        call_command("cleanup_old_notifications", days=90, dry_run=True, stdout=out)
        assert "[DRY-RUN] 1 read notification(s)" in out.getvalue()
        assert Notification.objects.filter(id=old_read.id).exists()

        # Actual deletion
        out = StringIO()
        call_command("cleanup_old_notifications", days=90, stdout=out)
        assert "Successfully deleted 1 read notification(s)" in out.getvalue()
        assert not Notification.objects.filter(id=old_read.id).exists()
        assert Notification.objects.filter(id=recent_read.id).exists()
        assert Notification.objects.filter(id=old_unread.id).exists()

    def test_notify_by_email_disabled_sends_zero_emails(self, user_factory, mailoutbox, settings):
        settings.NOTIFY_BY_EMAIL = False
        student = user_factory(email="no_email_student@example.com")

        create_notification(
            recipient=student,
            kind=Notification.Kind.DOWNLOAD_APPROVED,
            title="Approved File",
            body="You have access.",
            url="/learn/c/materials/",
        )
        assert len(mailoutbox) == 0

    def test_email_sending_failure_does_not_abort_transaction(self, user_factory, settings):
        settings.NOTIFY_BY_EMAIL = True
        student = user_factory(email="email_fail_student@example.com")

        with patch(
            "django.core.mail.EmailMultiAlternatives.send", side_effect=Exception("SMTP Down")
        ):
            notif = create_notification(
                recipient=student,
                kind=Notification.Kind.DOWNLOAD_APPROVED,
                title="Approved",
                body="Body",
                url="/learn/c/materials/",
            )
            # Notification is still successfully saved and persisted!
            assert Notification.objects.filter(id=notif.id).exists()
