import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress


@pytest.mark.django_db
class TestStudentDashboard:
    def test_empty_state_rendered_when_no_enrollments(self, client, user_factory):
        student = user_factory(role=User.Role.STUDENT)
        client.force_login(student)

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "You are not enrolled in any courses yet" in html
        assert reverse("courses:list") in html

    def test_active_and_pending_enrollments_displayed_and_revoked_hidden(
        self, client, user_factory
    ):
        student = user_factory(role=User.Role.STUDENT)
        client.force_login(student)

        course_active = Course.objects.create(
            title="Active Course Title",
            slug="active-course",
            is_published=True,
            is_free=True,
        )
        l1 = Lesson.objects.create(
            course=course_active,
            title="Lesson 1",
            order=1,
            is_published=True,
        )
        LessonProgress.objects.create(student=student, lesson=l1, last_position_seconds=42)

        course_pending = Course.objects.create(
            title="Pending Course Title",
            slug="pending-course",
            is_published=True,
            is_free=True,
        )

        course_revoked = Course.objects.create(
            title="Revoked Course Title",
            slug="revoked-course",
            is_published=True,
            is_free=True,
        )

        Enrollment.objects.create(
            student=student, course=course_active, status=Enrollment.Status.ACTIVE
        )
        Enrollment.objects.create(
            student=student, course=course_pending, status=Enrollment.Status.PENDING
        )
        Enrollment.objects.create(
            student=student, course=course_revoked, status=Enrollment.Status.REVOKED
        )

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # Active course rendered
        assert "Active Course Title" in html
        assert "Continue Learning" in html

        # Pending course rendered with badge
        assert "Pending Course Title" in html
        assert "Pending Teacher Review" in html

        # Revoked course NOT shown
        assert "Revoked Course Title" not in html

    def test_dashboard_query_count_does_not_grow_with_course_count(self, client, user_factory):
        """
        Asserts that the query count on /dashboard/student/ does not scale
        with the number of enrolled courses (O(1) query complexity).
        Compares query count with 1 course vs 10 courses.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        student_1 = user_factory(email="s1@example.com", role=User.Role.STUDENT)
        c1 = Course.objects.create(title="C1", slug="c1", is_published=True, is_free=True)
        Lesson.objects.create(course=c1, title="L1", order=1, is_published=True)
        Enrollment.objects.create(student=student_1, course=c1, status=Enrollment.Status.ACTIVE)

        client.force_login(student_1)
        # Warm up session/auth caches
        client.get(reverse("dashboard:student"))

        with CaptureQueriesContext(connection) as captured_1:
            client.get(reverse("dashboard:student"))
        query_count_1 = len(captured_1)

        # Student with 10 courses and multiple lessons each
        student_10 = user_factory(email="s10@example.com", role=User.Role.STUDENT)
        for i in range(2, 12):
            ci = Course.objects.create(
                title=f"Course {i}", slug=f"course-{i}", is_published=True, is_free=True
            )
            for order in range(1, 4):
                Lesson.objects.create(
                    course=ci, title=f"Lesson {order}", order=order, is_published=True
                )
            Enrollment.objects.create(
                student=student_10, course=ci, status=Enrollment.Status.ACTIVE
            )

        client.force_login(student_10)
        # Warm up
        client.get(reverse("dashboard:student"))

        with CaptureQueriesContext(connection) as captured_10:
            client.get(reverse("dashboard:student"))
        query_count_10 = len(captured_10)

        # Crucial check: 10 courses must take the EXACT same number of DB queries as 1 course!
        assert query_count_1 == query_count_10
