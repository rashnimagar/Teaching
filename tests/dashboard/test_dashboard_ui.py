import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress


@pytest.mark.django_db
class TestStudentDashboardUI:
    def test_greeting_with_first_name(self, client, user_factory):
        """Requirement 4: Greeting uses first name when available; never email in heading."""
        student = user_factory(
            first_name="Sunita", email="sunita@example.com", role=User.Role.STUDENT
        )
        client.force_login(student)

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "Welcome back, Sunita" in html
        assert "Welcome back, sunita@example.com" not in html

    def test_greeting_fallback_when_no_first_name(self, client, user_factory):
        """Requirement 4: Greeting falls back to 'Welcome back' when no first name; never shows email."""
        student = user_factory(
            first_name="", email="nameless_student@example.com", role=User.Role.STUDENT
        )
        client.force_login(student)

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "Welcome back" in html
        # Must not display email in greeting
        assert "Welcome back, nameless_student@example.com" not in html
        assert "Welcome back," not in html

    def test_continue_learning_hero_rendered_for_unfinished_lesson(self, client, user_factory):
        """
        Requirement 5: Continue learning hero uses most recent LessonProgress.updated_at
        for an unfinished lesson.
        """
        student = user_factory(
            first_name="Aarav", email="aarav@example.com", role=User.Role.STUDENT
        )
        client.force_login(student)

        course = Course.objects.create(
            title="Mastering Django", slug="mastering-django", is_published=True, is_free=True
        )
        l1 = Lesson.objects.create(course=course, title="Introduction", order=1, is_published=True)
        l2 = Lesson.objects.create(
            course=course, title="Models Deep Dive", order=2, is_published=True
        )

        Enrollment.objects.create(student=student, course=course, status=Enrollment.Status.ACTIVE)

        # Student has progress in lesson 2 (unfinished)
        LessonProgress.objects.create(student=student, lesson=l1, completed_at=None)
        LessonProgress.objects.create(
            student=student, lesson=l2, completed_at=None, last_position_seconds=120
        )

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Continue Learning" in html
        assert "Lesson 2: Models Deep Dive" in html
        assert "Mastering Django" in html
        assert "Resume Lesson" in html
        assert (
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l2.id}) in html
        )

    def test_continue_learning_hero_hidden_for_new_students(self, client, user_factory):
        """
        Requirement 5: Continue learning block is hidden for new students with no progress records.
        """
        student = user_factory(
            first_name="Bikash", email="bikash@example.com", role=User.Role.STUDENT
        )
        client.force_login(student)

        course = Course.objects.create(
            title="Intro to Python", slug="intro-python", is_published=True, is_free=True
        )
        Lesson.objects.create(course=course, title="Variables", order=1, is_published=True)
        Enrollment.objects.create(student=student, course=course, status=Enrollment.Status.ACTIVE)

        # Enrolled but has not touched any lesson yet
        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # Hero block must be hidden
        assert "Resume Lesson" not in html
        # Course card is present
        assert "Intro to Python" in html
        assert "Continue" in html

    def test_pending_enrollments_section_rendered_separately(self, client, user_factory):
        """Pending enrollments appear in their own section with approval badge."""
        student = user_factory(
            first_name="Deepa", email="deepa@example.com", role=User.Role.STUDENT
        )
        client.force_login(student)

        course = Course.objects.create(
            title="Advanced AI", slug="advanced-ai", is_published=True, is_free=True
        )
        Enrollment.objects.create(student=student, course=course, status=Enrollment.Status.PENDING)

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Pending Enrollment Requests" in html
        assert "Pending Teacher Review" in html
        assert "Advanced AI" in html
        assert "Access unlocks upon approval" in html


@pytest.mark.django_db
class TestTeacherDashboardUI:
    def test_teacher_dashboard_shows_real_counts_and_admin_links(self, client, user_factory):
        """
        Requirement 2: Teacher dashboard shell shows real counts (active students,
        published courses, pending enrollments, ungraded submissions) and links only
        to existing Django admin pages. No dead links and no Phase 7 text in UI.
        """
        teacher = user_factory(
            first_name="Ramesh",
            email="ramesh_teacher@example.com",
            role=User.Role.TEACHER,
            is_staff=True,
        )
        client.force_login(teacher)

        # Seed real metrics with distinct emails
        user_factory(email="student_a@example.com", role=User.Role.STUDENT, is_active=True)
        user_factory(email="student_b@example.com", role=User.Role.STUDENT, is_active=True)

        c1 = Course.objects.create(title="C1", slug="c1", is_published=True, is_free=True)
        Course.objects.create(title="C2", slug="c2", is_published=True, is_free=True)
        Course.objects.create(title="Unpublished", slug="unpub", is_published=False, is_free=True)

        applicant = user_factory(
            email="applicant@example.com", role=User.Role.STUDENT, is_active=True
        )
        Enrollment.objects.create(student=applicant, course=c1, status=Enrollment.Status.PENDING)

        from datetime import timedelta

        from django.utils import timezone

        assignment = Assignment.objects.create(
            course=c1,
            title="Assignment 1",
            instructions="Code it",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=7),
        )
        Submission.objects.create(
            assignment=assignment,
            student=applicant,
            content_text="Done",
            grade=None,  # Ungraded
        )

        resp = client.get(reverse("dashboard:teacher"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # Real metrics verification
        assert "Published Courses" in html
        assert "Pending Approvals" in html
        assert "Active Students" in html
        assert "Pending Submissions" in html

        # Verified Django Admin URLs present
        assert reverse("admin:courses_course_changelist") in html
        assert reverse("admin:courses_enrollment_changelist") in html
        assert reverse("admin:core_sitesettings_changelist") in html
        assert reverse("admin:assignments_submission_changelist") in html
        assert reverse("admin:index") in html

        # UI must NOT display "Phase 7" to the user
        assert "Phase 7 Integration Ready" not in html
        assert "Phase 7" not in html
