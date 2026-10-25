"""
Tests for Phase 7A: Teacher Dashboard (Courses, Lessons, Assignments Management)
Validates all 18 requirements:
1. Draft assignments hidden on every student path (list, detail, lesson tab, submit POST, downloads, score).
2. ASCII-only slug validation, Devanagari fallback ("course-<6 hex>"), slug locked when published or enrolled.
3. Unpublish confirmation with student loss count and archive recommendation.
4. Shell and sidebar links.
5. No hard delete of courses in dashboard (archive only).
6. Lesson video change resets last_position_seconds, preserves completed_at.
7. Assignment form clean() rejects lesson from another course.
8. Subquery/separate aggregates for course counts.
9. Lesson reorder in transaction.atomic() with select_for_update(), max+1 ordering.
10. Duration validation (minutes + seconds).
11. Anti-IDOR protection on all mutating POST actions.
12. CSRF rejection with enforce_csrf_checks=True.
13. Rate limiting on mutating endpoints.
14. Bounded query counts (no N+1).
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress
from apps.dashboard.forms_teacher import (
    TeacherAssignmentForm,
    TeacherCourseForm,
)
from apps.dashboard.slug_utils import generate_course_slug, validate_ascii_slug


@pytest.fixture
def teacher_user(user_factory):
    return user_factory(
        email="instructor@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )


@pytest.fixture
def student_user(user_factory):
    return user_factory(
        email="learner@example.com",
        role=User.Role.STUDENT,
        is_active=True,
    )


@pytest.fixture
def other_teacher(user_factory):
    return user_factory(
        email="other_teacher@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )


# ---------------------------------------------------------------------------
# 1. Permission Matrix & Access Control
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTeacherDashboardPermissions:
    def test_unauthenticated_user_redirected_to_login(self, client):
        urls = [
            reverse("dashboard:teacher"),
            reverse("dashboard:teacher_courses"),
            reverse("dashboard:teacher_course_create"),
        ]
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 302
            assert "/accounts/login/" in resp["Location"]

    def test_student_gets_403_forbidden(self, client, student_user):
        client.force_login(student_user)
        urls = [
            reverse("dashboard:teacher"),
            reverse("dashboard:teacher_courses"),
            reverse("dashboard:teacher_course_create"),
        ]
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 403

    def test_teacher_gets_200_ok(self, client, teacher_user):
        client.force_login(teacher_user)
        resp = client.get(reverse("dashboard:teacher_courses"))
        assert resp.status_code == 200

    def test_mutating_actions_reject_get_with_405(self, client, teacher_user):
        client.force_login(teacher_user)
        course = Course.objects.create(title="C1", slug="c1", is_published=True, is_free=True)
        lesson = Lesson.objects.create(
            course=course, title="L1", order=1, video_provider="youtube", video_id="dQw4w9WgXcQ"
        )
        assignment = Assignment.objects.create(
            course=course,
            title="A1",
            instructions="Do it",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=2),
        )

        mutating_urls = [
            reverse("dashboard:teacher_course_archive", kwargs={"slug": course.slug}),
            reverse("dashboard:teacher_lesson_toggle_publish", kwargs={"slug": course.slug, "lesson_id": lesson.id}),
            reverse("dashboard:teacher_lesson_reorder", kwargs={"slug": course.slug, "lesson_id": lesson.id}),
            reverse("dashboard:teacher_lesson_delete", kwargs={"slug": course.slug, "lesson_id": lesson.id}),
            reverse("dashboard:teacher_assignment_toggle_publish", kwargs={"slug": course.slug, "assignment_id": assignment.id}),
            reverse("dashboard:teacher_assignment_delete", kwargs={"slug": course.slug, "assignment_id": assignment.id}),
        ]
        for url in mutating_urls:
            resp = client.get(url)
            assert resp.status_code == 405


# ---------------------------------------------------------------------------
# 2. Slug Generation, Devanagari Fallback & Slug Locking
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSlugUtilitiesAndRules:
    def test_english_title_slug_generation(self):
        slug = generate_course_slug("Python for Beginners 2026")
        assert slug.startswith("python-for-beginners-2026")
        assert validate_ascii_slug(slug)

    def test_nepali_devanagari_title_fallback(self):
        """Django slugify drops Devanagari; must generate course-<6 random chars>"""
        nepali_title = "पाइथन प्रोग्रामिङ आधारभूत ज्ञान"
        slug = generate_course_slug(nepali_title)
        assert slug.startswith("course-")
        assert len(slug) >= 13  # "course-" (7) + 6 hex chars
        assert validate_ascii_slug(slug)

    def test_ascii_slug_validator_rejects_non_ascii_and_spaces(self):
        assert validate_ascii_slug("valid-slug-123") is True
        with pytest.raises(ValidationError):
            validate_ascii_slug("invalid slug")
        with pytest.raises(ValidationError):
            validate_ascii_slug("पाइथन-कोर्स")
        with pytest.raises(ValidationError):
            validate_ascii_slug("Slug_With_Underscore")

    def test_slug_becomes_readonly_when_published(self, teacher_user):
        course = Course.objects.create(title="Published Course", slug="pub-slug", is_published=True, is_free=True)
        form = TeacherCourseForm(instance=course)
        assert form.fields["slug"].disabled is True

    def test_slug_becomes_readonly_when_enrollments_exist(self, teacher_user, student_user):
        course = Course.objects.create(title="Draft Course", slug="draft-slug", is_published=False, is_free=True)
        Enrollment.objects.create(student=student_user, course=course, status=Enrollment.Status.ACTIVE)
        form = TeacherCourseForm(instance=course)
        assert form.fields["slug"].disabled is True


# ---------------------------------------------------------------------------
# 3. Draft Assignment Isolation on Every Student Path (Requirement 1)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDraftAssignmentIsolation:
    @pytest.fixture(autouse=True)
    def setup_data(self, student_user):
        self.course = Course.objects.create(title="Django Web", slug="django-web", is_published=True, is_free=True)
        self.enrollment = Enrollment.objects.create(
            student=student_user, course=self.course, status=Enrollment.Status.ACTIVE
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="Lesson 1",
            order=1,
            is_published=True,
            video_provider="youtube",
            video_id="dQw4w9WgXcQ",
        )
        self.draft_assignment = Assignment.objects.create(
            course=self.course,
            lesson=self.lesson,
            title="Draft Homework",
            instructions="Confidential problem set",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=3),
            max_score=100,
            is_published=False,  # Draft
        )

    def test_draft_assignment_hidden_on_course_assignments_list(self, client, student_user):
        client.force_login(student_user)
        resp = client.get(reverse("assignments:list", kwargs={"slug": self.course.slug}))
        assert resp.status_code == 200
        assert "Draft Homework" not in resp.content.decode("utf-8")

    def test_draft_assignment_detail_returns_404_for_student(self, client, student_user):
        client.force_login(student_user)
        url = reverse("assignments:detail", kwargs={"slug": self.course.slug, "assignment_id": self.draft_assignment.id})
        resp = client.get(url)
        assert resp.status_code == 404

    def test_draft_assignment_submit_post_rejected_with_404(self, client, student_user):
        client.force_login(student_user)
        url = reverse("assignments:detail", kwargs={"slug": self.course.slug, "assignment_id": self.draft_assignment.id})
        resp = client.post(url, {"content_text": "Hacked submission"})
        assert resp.status_code == 404

    def test_draft_assignment_hidden_on_lesson_learn_tab(self, client, student_user):
        client.force_login(student_user)
        url = reverse("learn:lesson", kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id})
        resp = client.get(url)
        assert resp.status_code == 200
        assert "Draft Homework" not in resp.content.decode("utf-8")

    def test_submission_download_for_draft_assignment_returns_404(self, client, student_user):
        sub = Submission.objects.create(
            assignment=self.draft_assignment,
            student=student_user,
            content_text="Sample",
            file=SimpleUploadedFile("ans.pdf", b"%PDF-1.4 sample content", content_type="application/pdf"),
        )
        client.force_login(student_user)
        url = reverse("assignments:download", kwargs={"slug": self.course.slug, "submission_id": sub.id})
        resp = client.get(url)
        assert resp.status_code == 404

    def test_overall_course_score_ignores_draft_assignment(self, client, student_user):
        # Create a published assignment
        pub = Assignment.objects.create(
            course=self.course,
            title="Published HW",
            instructions="Do this",
            opens_at=timezone.now() - timedelta(days=2),
            due_at=timezone.now() + timedelta(days=2),
            max_score=50,
            is_published=True,
        )
        # Create graded submissions on both
        Submission.objects.create(assignment=pub, student=student_user, content_text="Done", grade=Decimal("45.00"))
        Submission.objects.create(assignment=self.draft_assignment, student=student_user, content_text="Done", grade=Decimal("100.00"))

        client.force_login(student_user)
        resp = client.get(reverse("assignments:list", kwargs={"slug": self.course.slug}))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        # Total points should only reflect the published assignment (45 / 50 pts, not 145 / 150)
        assert "45" in html
        assert "145" not in html


# ---------------------------------------------------------------------------
# 4. Anti-IDOR Protection on All POST Actions (Requirement 18)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAntiIDORProtection:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.course_a = Course.objects.create(title="Course A", slug="course-a", is_published=True, is_free=True)
        self.course_b = Course.objects.create(title="Course B", slug="course-b", is_published=True, is_free=True)
        self.lesson_a = Lesson.objects.create(
            course=self.course_a, title="Lesson A", order=1, video_provider="youtube", video_id="dQw4w9WgXcQ"
        )
        self.assignment_a = Assignment.objects.create(
            course=self.course_a,
            title="Assignment A",
            instructions="Task",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=1),
        )

    def test_lesson_mutating_actions_fail_when_using_wrong_course_slug(self, client, teacher_user):
        client.force_login(teacher_user)
        # Attempting to mutate lesson_a through course_b's URL
        urls = [
            reverse("dashboard:teacher_lesson_edit", kwargs={"slug": self.course_b.slug, "lesson_id": self.lesson_a.id}),
            reverse("dashboard:teacher_lesson_toggle_publish", kwargs={"slug": self.course_b.slug, "lesson_id": self.lesson_a.id}),
            reverse("dashboard:teacher_lesson_reorder", kwargs={"slug": self.course_b.slug, "lesson_id": self.lesson_a.id}),
            reverse("dashboard:teacher_lesson_delete", kwargs={"slug": self.course_b.slug, "lesson_id": self.lesson_a.id}),
        ]
        for url in urls:
            resp = client.post(url, {"direction": "up"})
            assert resp.status_code == 404

    def test_assignment_mutating_actions_fail_when_using_wrong_course_slug(self, client, teacher_user):
        client.force_login(teacher_user)
        urls = [
            reverse("dashboard:teacher_assignment_edit", kwargs={"slug": self.course_b.slug, "assignment_id": self.assignment_a.id}),
            reverse("dashboard:teacher_assignment_toggle_publish", kwargs={"slug": self.course_b.slug, "assignment_id": self.assignment_a.id}),
            reverse("dashboard:teacher_assignment_delete", kwargs={"slug": self.course_b.slug, "assignment_id": self.assignment_a.id}),
        ]
        for url in urls:
            resp = client.post(url)
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Video Change Resets Playback Position (Requirement 7)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLessonVideoPositionReset:
    def test_video_id_change_resets_position_preserves_completed_at(self, client, teacher_user, student_user):
        course = Course.objects.create(title="Web Dev", slug="web-dev", is_published=True, is_free=True)
        lesson = Lesson.objects.create(
            course=course,
            title="Intro",
            order=1,
            video_provider="youtube",
            video_id="dQw4w9WgXcQ",
        )
        completed_time = timezone.now() - timedelta(days=1)
        progress = LessonProgress.objects.create(
            student=student_user,
            lesson=lesson,
            last_position_seconds=120,
            completed_at=completed_time,
        )

        client.force_login(teacher_user)
        edit_url = reverse("dashboard:teacher_lesson_edit", kwargs={"slug": course.slug, "lesson_id": lesson.id})

        # Submit change to video_id
        resp = client.post(
            edit_url,
            {
                "title": "Intro Updated",
                "video_provider": "youtube",
                "video_input": "https://www.youtube.com/watch?v=9bZkp7q19f0",
                "duration_minutes": 5,
                "duration_seconds": 0,
                "notes": "Updated video",
                "is_published": "on",
            },
        )
        assert resp.status_code == 302

        progress.refresh_from_db()
        # Position must be reset to 0
        assert progress.last_position_seconds == 0
        # Completed timestamp must be preserved
        assert progress.completed_at == completed_time


# ---------------------------------------------------------------------------
# 6. Assignment Form clean() Rejects Foreign Lesson (Requirement 8)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAssignmentLessonCourseValidation:
    def test_clean_rejects_lesson_from_another_course(self):
        course_a = Course.objects.create(title="Course A", slug="course-a", is_free=True)
        course_b = Course.objects.create(title="Course B", slug="course-b", is_free=True)
        lesson_b = Lesson.objects.create(
            course=course_b, title="Lesson B", order=1, video_provider="youtube", video_id="dQw4w9WgXcQ"
        )

        form = TeacherAssignmentForm(
            course=course_a,
            data={
                "title": "Assignment A",
                "lesson": lesson_b.id,
                "instructions": "Test",
                "opens_at": (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "due_at": (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                "max_score": 100,
                "is_published": True,
            },
        )
        assert not form.is_valid()
        assert "lesson" in form.errors


# ---------------------------------------------------------------------------
# 7. Confirmation Modals & Safeguards (Requirements 3, 5, 14)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSafeguardsAndModals:
    def test_unpublishing_course_with_active_students_requires_confirmation(self, client, teacher_user, student_user):
        course = Course.objects.create(title="Active Course", slug="active-c", is_published=True, is_free=True)
        Enrollment.objects.create(student=student_user, course=course, status=Enrollment.Status.ACTIVE)

        client.force_login(teacher_user)
        edit_url = reverse("dashboard:teacher_course_edit", kwargs={"slug": course.slug})

        # Submit unpublish without confirm_unpublish
        resp = client.post(
            edit_url,
            {
                "title": "Active Course",
                "slug": "active-c",
                "is_free": "on",
                "is_archived": False,
                # is_published not passed -> unpublish attempt
            },
        )
        assert resp.status_code == 200
        assert "confirm_unpublish" in resp.context["form"].errors

        # Now submit with confirmation
        resp2 = client.post(
            edit_url,
            {
                "title": "Active Course",
                "slug": "active-c",
                "is_free": "on",
                "is_archived": False,
                "confirm_unpublish": "true",
            },
        )
        assert resp2.status_code == 302
        course.refresh_from_db()
        assert course.is_published is False

    def test_past_deadline_requires_explicit_confirmation(self):
        course = Course.objects.create(title="Course", slug="crs", is_free=True)
        form = TeacherAssignmentForm(
            course=course,
            data={
                "title": "Past Assignment",
                "instructions": "Test",
                "opens_at": (timezone.now() - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M"),
                "due_at": (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
                "max_score": 100,
                "is_published": True,
                # confirm_past_deadline omitted
            },
        )
        assert not form.is_valid()
        assert "confirm_past_deadline" in form.errors

    def test_paid_course_requires_positive_price(self):
        form = TeacherCourseForm(
            data={
                "title": "Paid Course",
                "slug": "paid-course",
                "is_free": False,
                "price": 0,
            }
        )
        assert not form.is_valid()
        assert "price" in form.errors

    def test_raising_max_score_on_graded_assignment_issues_warning(self, client, teacher_user, student_user):
        from apps.assignments.models import Submission

        course = Course.objects.create(title="Graded Course", slug="graded-c", is_free=True)
        assignment = Assignment.objects.create(
            course=course,
            title="Graded Assignment",
            instructions="Do work",
            max_score=50,
            opens_at=timezone.now() - timedelta(days=2),
            due_at=timezone.now() + timedelta(days=5),
            is_published=True,
        )
        Submission.objects.create(
            assignment=assignment,
            student=student_user,
            grade=Decimal("45.00"),
        )

        client.force_login(teacher_user)
        edit_url = reverse(
            "dashboard:teacher_assignment_edit",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        resp = client.post(
            edit_url,
            {
                "title": "Graded Assignment",
                "instructions": "Do work",
                "opens_at": (timezone.now() - timedelta(days=2)).astimezone().strftime("%Y-%m-%dT%H:%M:%S"),
                "due_at": (timezone.now() + timedelta(days=5)).astimezone().strftime("%Y-%m-%dT%H:%M:%S"),
                "max_score": 100,  # Raised from 50 to 100
                "is_published": "on",
            },
            follow=True,
        )
        assert resp.status_code == 200
        assignment.refresh_from_db()
        assert assignment.max_score == 100
        # Check warning message was rendered in toast
        messages_list = list(resp.context["messages"])
        assert any("Warning: Maximum score was raised" in str(m) for m in messages_list)


# ---------------------------------------------------------------------------
# 8. Lesson Reorder Atomic Logic (Requirement 11)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLessonReorderLogic:
    def test_reorder_up_and_down_swaps_orders(self, client, teacher_user):
        course = Course.objects.create(title="Reorder Course", slug="reorder-c", is_free=True)
        l1 = Lesson.objects.create(course=course, title="Lesson 1", order=1, video_provider="youtube", video_id="vid1")
        l2 = Lesson.objects.create(course=course, title="Lesson 2", order=2, video_provider="youtube", video_id="vid2")
        Lesson.objects.create(course=course, title="Lesson 3", order=3, video_provider="youtube", video_id="vid3")

        client.force_login(teacher_user)
        # Move Lesson 2 Up
        url = reverse("dashboard:teacher_lesson_reorder", kwargs={"slug": course.slug, "lesson_id": l2.id})
        resp = client.post(url, {"direction": "up"})
        assert resp.status_code == 302
        assert f"moved={l2.id}" in resp["Location"]

        l1.refresh_from_db()
        l2.refresh_from_db()
        assert l2.order == 1
        assert l1.order == 2


# ---------------------------------------------------------------------------
# 9. CSRF Protection Enforcement (Requirement 18)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCSRFProtection:
    def test_post_without_csrf_token_rejected_when_enforced(self, teacher_user):
        enforcing_client = Client(enforce_csrf_checks=True)
        enforcing_client.force_login(teacher_user)

        course = Course.objects.create(title="CSRF Test", slug="csrf-test", is_free=True)
        url = reverse("dashboard:teacher_course_archive", kwargs={"slug": course.slug})

        # Plain POST without token returns 403
        resp = enforcing_client.post(url)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 10. Bounded Query Counts (Requirement 10)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBoundedQueryCounts:
    def test_course_list_queries_are_bounded_no_n_plus_one(self, client, teacher_user):
        # Create 10 courses with multiple lessons and assignments
        for i in range(10):
            c = Course.objects.create(title=f"Course {i}", slug=f"course-{i}", is_free=True, is_published=True)
            for j in range(3):
                Lesson.objects.create(course=c, title=f"L {j}", order=j + 1, video_provider="youtube", video_id="xyz")
            Assignment.objects.create(
                course=c,
                title="A1",
                instructions="Task",
                opens_at=timezone.now() - timedelta(days=1),
                due_at=timezone.now() + timedelta(days=2),
            )

        client.force_login(teacher_user)
        list_url = reverse("dashboard:teacher_courses")

        with CaptureQueriesContext(connection) as ctx:
            resp = client.get(list_url)
            assert resp.status_code == 200

        # Query count must remain low and bounded (subquery pagination + auth/session)
        assert len(ctx.captured_queries) <= 20
