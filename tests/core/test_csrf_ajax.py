import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadRequest,
    Enrollment,
    Lesson,
    LessonProgress,
    MaterialItem,
)


@override_settings(
    CSRF_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SECURE=False,  # Allow test client HTTP
)
class TestHttpOnlyCsrfAjaxActions(TestCase):
    """
    Validates that when CSRF_COOKIE_HTTPONLY is enabled (preventing document.cookie access),
    all client-side AJAX/POST actions work reliably by reading the CSRF token from the DOM
    (<meta name="csrf-token"> or form input) and passing it in HTTP headers or form data.
    """

    def setUp(self):
        self.student = User.objects.create_user(
            email="csrf_student@example.com",
            password="StrongPassword123!",
            role=User.Role.STUDENT,
        )
        self.teacher = User.objects.create_user(
            email="csrf_teacher@example.com",
            password="StrongPassword123!",
            role=User.Role.TEACHER,
            is_staff=True,
        )

        self.course = Course.objects.create(
            title="CSRF Hardened Course",
            slug="csrf-hardened-course",
            is_published=True,
        )
        self.enrollment = Enrollment.objects.create(student=self.student, course=self.course)

        self.lesson = Lesson.objects.create(
            course=self.course,
            title="CSRF Lesson 1",
            order=1,
            is_published=True,
            video_id="dQw4w9WgXcQ",
            video_provider=Lesson.VideoProvider.YOUTUBE,
        )

        self.mat = CourseMaterial.objects.create(
            course=self.course,
            title="Supplemental Materials",
            is_published=True,
        )
        pdf_file = SimpleUploadedFile("guide.pdf", b"%PDF-1.4...", content_type="application/pdf")
        self.req_item = MaterialItem.objects.create(
            material=self.mat,
            title="Restricted Syllabus",
            item_type=MaterialItem.ItemType.FILE,
            file=pdf_file,
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            is_published=True,
        )

    def _get_csrf_client(self, user) -> tuple[Client, str]:
        """
        Creates a test client with enforce_csrf_checks=True, authenticates user,
        fetches a page to initiate the HttpOnly session and CSRF cookie,
        and extracts the CSRF token from the <meta name="csrf-token"> element in DOM.
        """
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)

        # GET page to trigger CSRF cookie generation and render meta tag
        resp = client.get(reverse("courses:detail", kwargs={"slug": self.course.slug}))
        assert resp.status_code == 200

        # Assert cookie is present
        assert "csrftoken" in client.cookies
        assert client.cookies["csrftoken"]["httponly"] is True, (
            "CSRF cookie must have HttpOnly flag"
        )

        # Extract token from DOM <meta name="csrf-token" content="...">
        html = resp.content.decode("utf-8")
        match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
        assert match is not None, (
            "Page must include <meta name='csrf-token'> for HttpOnly token extraction"
        )
        token = match.group(1)
        assert len(token) > 20
        return client, token

    def test_lesson_toggle_complete_with_httponly_csrf(self):
        """Student marks lesson complete using token from meta tag via X-CSRFToken header."""
        client, token = self._get_csrf_client(self.student)
        url = reverse(
            "learn:toggle_complete",
            kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
        )

        # POST with X-CSRFToken header
        resp = client.post(url, HTTP_X_CSRFTOKEN=token)
        assert resp.status_code in (200, 302)

        progress = LessonProgress.objects.get(student=self.student, lesson=self.lesson)
        assert progress.completed_at is not None

    def test_playback_position_heartbeat_with_httponly_csrf(self):
        """Video player sends playback heartbeat with X-CSRFToken header."""
        client, token = self._get_csrf_client(self.student)
        url = reverse(
            "learn:playback_position",
            kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
        )

        resp = client.post(url, {"position": 145}, HTTP_X_CSRFTOKEN=token)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "position": 145}

        progress = LessonProgress.objects.get(student=self.student, lesson=self.lesson)
        assert progress.last_position_seconds == 145

    def test_material_request_and_cancel_with_httponly_csrf(self):
        """Student requests and cancels material download using HttpOnly CSRF."""
        client, token = self._get_csrf_client(self.student)

        # 1. Request download
        req_url = reverse(
            "learn:material_request",
            kwargs={"course_slug": self.course.slug, "item_id": self.req_item.id},
        )
        resp_req = client.post(req_url, HTTP_X_CSRFTOKEN=token)
        assert resp_req.status_code == 302

        d_req = DownloadRequest.objects.get(student=self.student, material_item=self.req_item)
        assert d_req.status == DownloadRequest.Status.PENDING

        # 2. Cancel download
        cancel_url = reverse(
            "learn:material_cancel",
            kwargs={"course_slug": self.course.slug, "item_id": self.req_item.id},
        )
        resp_cancel = client.post(cancel_url, HTTP_X_CSRFTOKEN=token)
        assert resp_cancel.status_code == 302
        assert not DownloadRequest.objects.filter(id=d_req.id).exists()

    def test_teacher_dashboard_post_with_httponly_csrf(self):
        """Teacher performs dashboard mutation using DOM CSRF token."""
        client, token = self._get_csrf_client(self.teacher)

        url = reverse(
            "dashboard:teacher_material_item_policy",
            kwargs={
                "slug": self.course.slug,
                "material_id": self.mat.id,
                "item_id": self.req_item.id,
            },
        )
        resp = client.post(url, {"target_policy": "open_to_enrolled"}, HTTP_X_CSRFTOKEN=token)
        assert resp.status_code == 302

        self.req_item.refresh_from_db()
        assert self.req_item.download_policy == MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED

    def test_missing_or_tampered_csrf_rejected_with_403(self):
        """Enforces that without valid token, POST actions are strictly rejected with 403."""
        client, _ = self._get_csrf_client(self.student)
        url = reverse(
            "learn:playback_position",
            kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
        )

        # Missing token
        resp_missing = client.post(url, {"position": 50})
        assert resp_missing.status_code == 403

        # Tampered token
        resp_tampered = client.post(
            url, {"position": 50}, HTTP_X_CSRFTOKEN="invalid-tampered-token-12345"
        )
        assert resp_tampered.status_code == 403
