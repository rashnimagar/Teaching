from pathlib import Path

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.models import User
from apps.core.views import csrf_failure, handler403


@pytest.mark.django_db
class TestErrorPages:
    def test_500_template_renders_with_zero_context(self):
        """
        Requirement 8: 500.html has no {% static %}, no {% url %}, no context processors
        and inline CSS only. It must render cleanly with an empty context dict {}.
        """
        template_path = Path("templates/500.html")
        assert template_path.exists(), "500.html template must exist"
        raw_content = template_path.read_text(encoding="utf-8")

        # Must not contain Django tags requiring context or staticfiles
        assert "{% static" not in raw_content, "500.html must not use {% static %}"
        assert "{% url" not in raw_content, "500.html must not use {% url %}"
        assert "{% extends" not in raw_content, "500.html must be a standalone file without extends"

        # Must render cleanly with empty context
        rendered = render_to_string("500.html", {})
        assert "500" in rendered
        assert "Unexpected Server Error" in rendered
        assert "<style>" in rendered

    def test_403_page_guest_sees_login(self, client):
        """
        Requirement 9: On 403 page, unauthenticated guests see 'Log in' CTA.
        """
        rf = RequestFactory()
        request = rf.get("/some-restricted-path/")
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()

        response = handler403(request)
        assert response.status_code == 403
        content = response.content.decode("utf-8")
        assert "Log in" in content
        assert reverse("account_login") in content
        assert "Go to My Dashboard" not in content

    def test_403_page_authenticated_student_sees_dashboard(self, client, user_factory):
        """
        Requirement 9: On 403 page, logged-in students see 'Go to My Dashboard'.
        """
        student = user_factory(role=User.Role.STUDENT, first_name="Aarav")
        client.force_login(student)

        rf = RequestFactory()
        request = rf.get("/some-restricted-path/")
        request.user = student

        response = handler403(request)
        assert response.status_code == 403
        content = response.content.decode("utf-8")
        assert "Go to My Dashboard" in content
        assert reverse("dashboard:student") in content
        assert "Log in" not in content

    def test_403_page_authenticated_teacher_sees_teacher_dashboard(self, client, user_factory):
        """
        Requirement 9: On 403 page, logged-in teachers see 'Go to Teacher Dashboard'.
        """
        teacher = user_factory(role=User.Role.TEACHER, first_name="Prof")
        client.force_login(teacher)

        rf = RequestFactory()
        request = rf.get("/some-restricted-path/")
        request.user = teacher

        response = handler403(request)
        assert response.status_code == 403
        content = response.content.decode("utf-8")
        assert "Go to Teacher Dashboard" in content
        assert reverse("dashboard:teacher") in content

    def test_csrf_failure_view(self):
        """
        Requirement 8: Style CSRF_FAILURE_VIEW and ensure it returns HTTP 403 with styled guidance.
        """
        rf = RequestFactory()
        request = rf.post("/accounts/login/")
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()

        response = csrf_failure(request, reason="CSRF token missing")
        assert response.status_code == 403
        content = response.content.decode("utf-8")
        assert "Session Expired" in content
        assert "Refresh &amp; Try Again" in content or "Refresh" in content
