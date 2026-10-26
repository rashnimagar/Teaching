import csv
import io
import logging
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.admin import SubmissionAdmin
from apps.assignments.models import Assignment, Submission, SubmissionEvent
from apps.assignments.services.grading import grade_submission, unlock_submission
from apps.courses.models import Course, Enrollment, EnrollmentEvent, Lesson, LessonProgress
from apps.courses.services.enrollments import (
    ALLOWED_ENROLLMENT_TRANSITIONS,
    transition_enrollment_status,
)
from apps.dashboard.reports import sanitize_csv_cell
from apps.notifications.models import Notification


@pytest.fixture(autouse=True)
def clear_ratelimit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def teacher_user(user_factory):
    return user_factory(
        email="teacher_7b@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )


@pytest.fixture
def student_user(user_factory):
    return user_factory(
        email="student_7b@example.com",
        role=User.Role.STUDENT,
        is_active=True,
    )


@pytest.fixture
def course():
    return Course.objects.create(
        title="Django Masterclass",
        slug="django-masterclass",
        is_published=True,
        is_free=True,
    )


@pytest.fixture
def assignment(course):
    now = timezone.now()
    return Assignment.objects.create(
        course=course,
        title="Final Project",
        instructions="Submit your repository",
        max_score=Decimal("100.00"),
        opens_at=now - timedelta(days=2),
        due_at=now + timedelta(days=5),
        is_published=True,
    )


# ---------------------------------------------------------------------------
# 1. Formula Injection & CSV Sanitization (CWE-1236)
# ---------------------------------------------------------------------------
class TestCSVFormulaInjectionAndExport:
    def test_sanitize_csv_cell_prepends_quote_to_formula_triggers(self):
        """Every cell starting with =, +, -, @, tab, or carriage return gets a leading single quote."""
        assert sanitize_csv_cell("=CMD('calc')") == "'=CMD('calc')"
        assert sanitize_csv_cell("+12345") == "'+12345"
        assert sanitize_csv_cell("-SOMETHING") == "'-SOMETHING"
        assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
        assert sanitize_csv_cell("\tMALICIOUS") == "'\tMALICIOUS"
        assert sanitize_csv_cell("\rINJECT") == "'\rINJECT"

        # Harmless cells are unchanged
        assert sanitize_csv_cell("Normal Text") == "Normal Text"
        assert sanitize_csv_cell("100.00") == "100.00"
        assert sanitize_csv_cell("") == ""
        assert sanitize_csv_cell(None) == ""

    def test_grades_csv_export_with_malicious_names_and_nepali(
        self, client, teacher_user, course, assignment, user_factory
    ):
        """Grades export correctly sanitizes formulas, outputs UTF-8 BOM, and preserves Nepali text."""
        nepali_student = user_factory(
            first_name="राम",
            last_name="शर्मा",
            email="ram_nepali@example.com",
            role=User.Role.STUDENT,
        )
        malicious_student = user_factory(
            first_name="=HYPERLINK('http://evil.com')",
            last_name="Test",
            email="evil@example.com",
            role=User.Role.STUDENT,
        )
        cmd_student = user_factory(
            first_name="+CMD",
            last_name="Exec",
            email="cmd@example.com",
            role=User.Role.STUDENT,
        )

        Enrollment.objects.create(student=nepali_student, course=course, status=Enrollment.Status.ACTIVE)
        Enrollment.objects.create(student=malicious_student, course=course, status=Enrollment.Status.ACTIVE)
        Enrollment.objects.create(student=cmd_student, course=course, status=Enrollment.Status.ACTIVE)

        Submission.objects.create(
            assignment=assignment,
            student=nepali_student,
            grade=Decimal("95.00"),
            feedback="उत्कृष्ट काम भयो!",
        )
        Submission.objects.create(
            assignment=assignment,
            student=malicious_student,
            grade=Decimal("50.00"),
            feedback="@SUM(1,2)",
        )

        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_course_grades_export", kwargs={"slug": course.slug})
        resp = client.get(url)

        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv; charset=utf-8"
        assert "private, no-store" in resp["Cache-Control"]
        assert "attachment; filename=" in resp["Content-Disposition"]

        content = b"".join(resp.streaming_content).decode("utf-8")
        assert content.startswith("\ufeff")  # UTF-8 BOM

        # Verify Nepali is present
        assert "राम शर्मा" in content

        # Verify malicious formulas are sanitized with leading quote
        assert "'=HYPERLINK" in content
        assert "'+CMD" in content

    def test_progress_csv_export_counts_only_published_lessons(
        self, client, teacher_user, course, user_factory
    ):
        """Progress CSV counts completed published lessons and excludes draft lessons."""
        l1 = Lesson.objects.create(course=course, title="Lesson 1", order=1, is_published=True)
        l2 = Lesson.objects.create(course=course, title="Lesson 2", order=2, is_published=True)
        l3_draft = Lesson.objects.create(course=course, title="Lesson 3 Draft", order=3, is_published=False)

        student = user_factory(email="learner@example.com", role=User.Role.STUDENT)
        Enrollment.objects.create(student=student, course=course, status=Enrollment.Status.ACTIVE)

        # Mark l1 and draft l3 completed
        LessonProgress.objects.create(student=student, lesson=l1, completed_at=timezone.now())
        LessonProgress.objects.create(student=student, lesson=l3_draft, completed_at=timezone.now())

        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_course_progress_export", kwargs={"slug": course.slug})
        resp = client.get(url)
        assert resp.status_code == 200

        content = b"".join(resp.streaming_content).decode("utf-8")
        reader = csv.reader(io.StringIO(content.lstrip("\ufeff")))
        rows = list(reader)
        header = rows[0]
        assert "Completed Lessons" in header
        assert "Total Published Lessons" in header

        # Student row: completed=1, total=2 (50.0%)
        student_row = next(r for r in rows[1:] if "learner@example.com" in r)
        completed_idx = header.index("Completed Lessons")
        total_idx = header.index("Total Published Lessons")
        pct_idx = header.index("Progress (%)")

        assert student_row[completed_idx] == "1"
        assert student_row[total_idx] == "2"
        assert student_row[pct_idx] == "50.0%"


# ---------------------------------------------------------------------------
# 2. Enrollment Transitions & Audit Events
# ---------------------------------------------------------------------------
class TestEnrollmentTransitionsAndAudit:
    def test_allowed_transitions_create_enrollment_events(self, teacher_user, student_user, course):
        """Allowed transitions (pending->active, active->revoked, revoked->active) write EnrollmentEvent rows."""
        enrollment = Enrollment.objects.create(
            student=student_user,
            course=course,
            status=Enrollment.Status.PENDING,
        )

        # 1. pending -> active
        enr, success, msg = transition_enrollment_status(
            enrollment_id=enrollment.id,
            new_status=Enrollment.Status.ACTIVE,
            actor=teacher_user,
            note="Approved by instructor",
        )
        assert success is True
        assert enr.status == Enrollment.Status.ACTIVE
        evt1 = EnrollmentEvent.objects.filter(enrollment=enr).latest("created_at")
        assert evt1.from_status == Enrollment.Status.PENDING
        assert evt1.to_status == Enrollment.Status.ACTIVE
        assert evt1.actor == teacher_user
        assert evt1.note == "Approved by instructor"

        # 2. active -> revoked
        enr, success, msg = transition_enrollment_status(
            enrollment_id=enrollment.id,
            new_status=Enrollment.Status.REVOKED,
            actor=teacher_user,
            note="Violated rules",
        )
        assert success is True
        assert enr.status == Enrollment.Status.REVOKED
        evt2 = EnrollmentEvent.objects.filter(enrollment=enr).latest("created_at")
        assert evt2.from_status == Enrollment.Status.ACTIVE
        assert evt2.to_status == Enrollment.Status.REVOKED

        # 3. revoked -> active
        enr, success, msg = transition_enrollment_status(
            enrollment_id=enrollment.id,
            new_status=Enrollment.Status.ACTIVE,
            actor=teacher_user,
            note="Restored on appeal",
        )
        assert success is True
        assert enr.status == Enrollment.Status.ACTIVE
        assert EnrollmentEvent.objects.filter(enrollment=enr).count() == 3

    def test_invalid_transitions_are_rejected(self, teacher_user, student_user, course):
        """Disallowed transitions (e.g. active->pending, revoked->pending) raise ValueError."""
        enrollment = Enrollment.objects.create(
            student=student_user,
            course=course,
            status=Enrollment.Status.ACTIVE,
        )
        with pytest.raises(ValueError, match="Invalid enrollment status transition"):
            transition_enrollment_status(
                enrollment_id=enrollment.id,
                new_status=Enrollment.Status.PENDING,
                actor=teacher_user,
            )

    def test_revoke_and_restore_never_touch_progress_or_submissions(
        self, teacher_user, student_user, course, assignment
    ):
        """Revoking an enrollment and restoring it preserves student submissions and lesson progress."""
        enrollment = Enrollment.objects.create(
            student=student_user, course=course, status=Enrollment.Status.ACTIVE
        )
        lesson = Lesson.objects.create(course=course, title="L1", is_published=True)
        LessonProgress.objects.create(student=student_user, lesson=lesson, completed_at=timezone.now())
        sub = Submission.objects.create(
            assignment=assignment, student=student_user, grade=Decimal("90.00")
        )

        # Revoke
        transition_enrollment_status(enrollment.id, Enrollment.Status.REVOKED, teacher_user)
        assert LessonProgress.objects.filter(student=student_user, lesson=lesson).exists()
        assert Submission.objects.filter(id=sub.id).exists()

        # Restore
        transition_enrollment_status(enrollment.id, Enrollment.Status.ACTIVE, teacher_user)
        assert LessonProgress.objects.filter(student=student_user, lesson=lesson).exists()
        assert Submission.objects.filter(id=sub.id).exists()


# ---------------------------------------------------------------------------
# 3. Manual Enrollment
# ---------------------------------------------------------------------------
class TestManualEnrollment:
    def test_manual_enrollment_requires_existing_student_account(self, client, teacher_user, course):
        """Manual enrollment returns clear error if student account does not exist."""
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_enrollment_manual")
        resp = client.post(
            url,
            {"email": "nonexistent_student@example.com", "course_id": course.id},
            follow=True,
        )
        assert resp.status_code == 200
        messages = list(resp.context["messages"])
        assert any("No student account found" in str(m) for m in messages)
        assert not Enrollment.objects.filter(course=course).exists()

    def test_manual_enrollment_succeeds_with_existing_student(
        self, client, teacher_user, student_user, course
    ):
        """Manual enrollment creates active enrollment using get_or_create and logs EnrollmentEvent."""
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_enrollment_manual")
        resp = client.post(
            url,
            {"email": student_user.email, "course_id": course.id},
            follow=True,
        )
        assert resp.status_code == 200
        enr = Enrollment.objects.get(student=student_user, course=course)
        assert enr.status == Enrollment.Status.ACTIVE
        assert enr.source == Enrollment.Source.MANUAL

        # Event logged
        evt = EnrollmentEvent.objects.get(enrollment=enr)
        assert evt.from_status == "none"
        assert evt.to_status == Enrollment.Status.ACTIVE
        assert evt.actor == teacher_user


# ---------------------------------------------------------------------------
# 4. Grading Service, Regrading Rules & Save & Next
# ---------------------------------------------------------------------------
class TestGradingServiceAndRegradeRules:
    def test_grade_submission_validates_score_bounds(self, teacher_user, student_user, assignment):
        """Grades must be between 0 and assignment.max_score."""
        sub = Submission.objects.create(assignment=assignment, student=student_user)

        # Negative grade
        with pytest.raises(Exception):
            grade_submission(sub.id, Decimal("-5.00"), "Too low", teacher_user)

        # Above max score
        with pytest.raises(Exception):
            grade_submission(sub.id, Decimal("150.00"), "Too high", teacher_user)

    def test_regrade_updates_audit_fields_only_on_grade_change(
        self, teacher_user, student_user, assignment, user_factory, django_capture_on_commit_callbacks
    ):
        """graded_by and graded_at change ONLY when numeric grade changes; student notified only then."""
        sub = Submission.objects.create(assignment=assignment, student=student_user)

        # 1. Initial Grade
        with django_capture_on_commit_callbacks(execute=True):
            sub, success, _ = grade_submission(sub.id, Decimal("75.00"), "Good attempt", teacher_user)
        initial_graded_at = sub.graded_at
        initial_graded_by = sub.graded_by
        assert sub.grade == Decimal("75.00")
        assert initial_graded_at is not None
        assert initial_graded_by == teacher_user

        # Notification created
        assert Notification.objects.filter(
            recipient=student_user, kind=Notification.Kind.SUBMISSION_GRADED
        ).count() == 1

        # 2. Update Feedback ONLY (grade remains 75.00) with a different teacher
        another_teacher = user_factory(email="another_teacher@example.com", role=User.Role.TEACHER)
        with django_capture_on_commit_callbacks(execute=True):
            sub, success, _ = grade_submission(sub.id, Decimal("75.00"), "Updated feedback only", another_teacher)

        # graded_at and graded_by MUST remain unchanged!
        assert sub.graded_at == initial_graded_at
        assert sub.graded_by == initial_graded_by
        assert sub.feedback == "Updated feedback only"

        # No duplicate notification sent
        assert Notification.objects.filter(
            recipient=student_user, kind=Notification.Kind.SUBMISSION_GRADED
        ).count() == 1

        # 3. Numeric Grade Changes to 85.00
        with django_capture_on_commit_callbacks(execute=True):
            sub, success, _ = grade_submission(sub.id, Decimal("85.00"), "Revised score", another_teacher)
        assert sub.grade == Decimal("85.00")
        assert sub.graded_by == another_teacher
        assert sub.graded_at > initial_graded_at

        # Second notification sent on actual grade change
        assert Notification.objects.filter(
            recipient=student_user, kind=Notification.Kind.SUBMISSION_GRADED
        ).count() == 2

    def test_notification_sent_on_commit_and_failure_isolated(
        self, teacher_user, student_user, course, assignment, django_capture_on_commit_callbacks, monkeypatch
    ):
        """Notifications are dispatched with transaction.on_commit, and failure never blocks or rolls back."""
        enrollment = Enrollment.objects.create(
            student=student_user, course=course, status=Enrollment.Status.PENDING
        )

        # 1. Normal transition triggers on_commit notification
        with django_capture_on_commit_callbacks(execute=True):
            enr, success, _ = transition_enrollment_status(
                enrollment.id, Enrollment.Status.ACTIVE, teacher_user
            )
        assert success is True
        assert enr.status == Enrollment.Status.ACTIVE
        assert Notification.objects.filter(
            recipient=student_user, kind=Notification.Kind.ENROLLMENT_APPROVED
        ).count() == 1

        # 2. Simulate notification failure (e.g. notification service raises Exception)
        def broken_create_notification(*args, **kwargs):
            raise RuntimeError("Notification backend failure simulated")

        monkeypatch.setattr("apps.courses.services.enrollments.create_notification", broken_create_notification)
        monkeypatch.setattr("apps.assignments.services.grading.create_notification", broken_create_notification)

        # Transition to revoked with broken notifications
        with django_capture_on_commit_callbacks(execute=True):
            enr_revoked, rev_success, _ = transition_enrollment_status(
                enrollment.id, Enrollment.Status.REVOKED, teacher_user
            )
        # Action succeeded and was NOT rolled back or blocked!
        assert rev_success is True
        assert enr_revoked.status == Enrollment.Status.REVOKED
        enrollment.refresh_from_db()
        assert enrollment.status == Enrollment.Status.REVOKED

        # Submission grading with broken notifications
        sub = Submission.objects.create(assignment=assignment, student=student_user)
        with django_capture_on_commit_callbacks(execute=True):
            sub_graded, grade_success, _ = grade_submission(
                sub.id, Decimal("95.00"), "Superb work", teacher_user
            )
        # Action succeeded and was NOT rolled back or blocked!
        assert grade_success is True
        assert sub_graded.grade == Decimal("95.00")
        sub.refresh_from_db()
        assert sub.grade == Decimal("95.00")

    def test_save_and_next_redirects_to_next_ungraded(
        self, client, teacher_user, student_user, user_factory, assignment
    ):
        """Save & next ungraded advances to the next ungraded submission."""
        student2 = user_factory(email="student2@example.com", role=User.Role.STUDENT)
        sub1 = Submission.objects.create(assignment=assignment, student=student_user)
        sub2 = Submission.objects.create(assignment=assignment, student=student2)

        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_submission_grade", kwargs={"submission_id": sub1.id})

        resp = client.post(
            url,
            {"grade": "88.00", "feedback": "Great", "save_and_next": "1"},
        )
        assert resp.status_code == 302
        expected_next = reverse("dashboard:teacher_submission_grade", kwargs={"submission_id": sub2.id})
        assert resp.url == expected_next

    def test_unlock_action_allows_resubmission_and_records_audit(
        self, client, teacher_user, student_user, assignment
    ):
        """Unlocking sets is_unlocked=True, records audit event, and allows student to resubmit."""
        sub = Submission.objects.create(assignment=assignment, student=student_user)

        client.force_login(teacher_user)
        unlock_url = reverse("dashboard:teacher_submission_unlock", kwargs={"submission_id": sub.id})
        resp = client.post(unlock_url, {"note": "Resubmission permitted for corrections"})
        assert resp.status_code == 302

        sub.refresh_from_db()
        assert sub.is_unlocked is True
        evt = SubmissionEvent.objects.filter(submission=sub, action="unlocked").first()
        assert evt is not None
        assert evt.actor == teacher_user
        assert evt.note == "Resubmission permitted for corrections"

    def test_unlock_overrides_deadline_and_resubmission_resets_grade(
        self, client, teacher_user, student_user, course, user_factory
    ):
        """
        Unlocking overrides the deadline rule for that submission (even when allow_late is False).
        On resubmission, the old grade is reset to None and teacher sees it needs review in the queue.
        """
        now = timezone.now()
        strict_assignment = Assignment.objects.create(
            course=course,
            title="Strict Assignment",
            max_score=Decimal("100.00"),
            opens_at=now - timedelta(days=5),
            due_at=now - timedelta(days=2),  # Deadline passed
            allow_late=False,  # Late submissions disallowed
            is_published=True,
        )
        Enrollment.objects.create(student=student_user, course=course, status=Enrollment.Status.ACTIVE)

        # Existing graded submission
        sub = Submission.objects.create(
            assignment=strict_assignment,
            student=student_user,
            content_text="Initial response",
            grade=Decimal("65.00"),
            graded_by=teacher_user,
            graded_at=now - timedelta(days=1),
            is_unlocked=False,
        )

        # 1. Student attempts to edit while locked -> rejected
        client.force_login(student_user)
        detail_url = reverse("assignments:detail", kwargs={"slug": course.slug, "assignment_id": strict_assignment.id})
        resp_blocked = client.post(detail_url, {"content_text": "Unauthorized edit"})
        assert resp_blocked.status_code == 302
        sub.refresh_from_db()
        assert sub.content_text == "Initial response"
        assert sub.grade == Decimal("65.00")

        # 2. Teacher unlocks the submission
        client.force_login(teacher_user)
        unlock_url = reverse("dashboard:teacher_submission_unlock", kwargs={"submission_id": sub.id})
        client.post(unlock_url, {"note": "Unlocked for corrections after deadline"})
        sub.refresh_from_db()
        assert sub.is_unlocked is True

        # 3. Student resubmits past deadline with allow_late=False -> allowed!
        client.force_login(student_user)
        resp_allowed = client.post(detail_url, {"content_text": "Corrected and updated work"})
        assert resp_allowed.status_code == 302

        # 4. Old grade is reset to None, is_unlocked is reset to False
        sub.refresh_from_db()
        assert sub.content_text == "Corrected and updated work"
        assert sub.grade is None
        assert sub.graded_by is None
        assert sub.is_unlocked is False

        # 5. SubmissionEvent with action="resubmitted" is recorded
        resub_evt = SubmissionEvent.objects.filter(submission=sub, action="resubmitted").first()
        assert resub_evt is not None
        assert resub_evt.actor == student_user
        assert resub_evt.old_grade == Decimal("65.00")

        # 6. Teacher sees it in the submissions queue as needing review (grade__isnull=True)
        client.force_login(teacher_user)
        queue_url = reverse("dashboard:teacher_submissions")
        queue_resp = client.get(queue_url)
        assert queue_resp.status_code == 200
        assert sub in queue_resp.context["submissions"]

    def test_django_admin_uses_grading_service(self, teacher_user, student_user, assignment):
        """The Django admin SubmissionAdmin uses grade_submission and creates audit events."""
        sub = Submission.objects.create(assignment=assignment, student=student_user)
        sub.grade = Decimal("92.00")
        sub.feedback = "Graded via Admin"

        site = AdminSite()
        admin_obj = SubmissionAdmin(Submission, site)

        from unittest.mock import MagicMock
        req = MagicMock()
        req.user = teacher_user

        admin_obj.save_model(req, sub, form=None, change=True)

        sub.refresh_from_db()
        assert sub.grade == Decimal("92.00")
        assert sub.graded_by == teacher_user
        assert SubmissionEvent.objects.filter(submission=sub, action="graded").exists()


# ---------------------------------------------------------------------------
# 5. Account Deactivation Guards
# ---------------------------------------------------------------------------
class TestAccountDeactivationGuards:
    def test_teacher_cannot_deactivate_self(self, client, teacher_user):
        """Teacher cannot deactivate their own account."""
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_student_toggle_active", kwargs={"student_id": teacher_user.id})
        resp = client.post(url, follow=True)
        assert resp.status_code == 200
        teacher_user.refresh_from_db()
        assert teacher_user.is_active is True
        messages = list(resp.context["messages"])
        assert any("cannot deactivate your own account" in str(m) for m in messages)

    def test_teacher_cannot_deactivate_other_teachers_or_superusers(
        self, client, teacher_user, user_factory
    ):
        """Teacher cannot deactivate other teachers or superusers."""
        other_teacher = user_factory(email="other_t@example.com", role=User.Role.TEACHER, is_active=True)
        superuser = user_factory(email="root@example.com", is_superuser=True, is_active=True)

        client.force_login(teacher_user)

        # Attempt on other teacher
        url1 = reverse("dashboard:teacher_student_toggle_active", kwargs={"student_id": other_teacher.id})
        resp1 = client.post(url1, follow=True)
        other_teacher.refresh_from_db()
        assert other_teacher.is_active is True

        # Attempt on superuser
        url2 = reverse("dashboard:teacher_student_toggle_active", kwargs={"student_id": superuser.id})
        resp2 = client.post(url2, follow=True)
        superuser.refresh_from_db()
        assert superuser.is_active is True

    def test_teacher_can_deactivate_and_reactivate_student(
        self, client, teacher_user, student_user
    ):
        """Teacher can successfully toggle a student's active status."""
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_student_toggle_active", kwargs={"student_id": student_user.id})

        # Deactivate
        resp = client.post(url, follow=True)
        assert resp.status_code == 200
        student_user.refresh_from_db()
        assert student_user.is_active is False

        # Reactivate
        resp = client.post(url, follow=True)
        assert resp.status_code == 200
        student_user.refresh_from_db()
        assert student_user.is_active is True


# ---------------------------------------------------------------------------
# 6. Missed Deadlines & IDOR Guards
# ---------------------------------------------------------------------------
class TestMissedDeadlinesAndIDOR:
    def test_missed_deadlines_identifies_unsubmitted_active_students(
        self, client, teacher_user, course, user_factory
    ):
        """Shows active students without submission after due_at."""
        now = timezone.now()
        past_assignment = Assignment.objects.create(
            course=course,
            title="Past Due Assignment",
            opens_at=now - timedelta(days=5),
            due_at=now - timedelta(days=1),
            allow_late=True,
            is_published=True,
        )

        s_submitted = user_factory(email="submitted@example.com", role=User.Role.STUDENT)
        s_unsubmitted = user_factory(email="missing@example.com", role=User.Role.STUDENT)

        Enrollment.objects.create(student=s_submitted, course=course, status=Enrollment.Status.ACTIVE)
        Enrollment.objects.create(student=s_unsubmitted, course=course, status=Enrollment.Status.ACTIVE)

        Submission.objects.create(assignment=past_assignment, student=s_submitted)

        client.force_login(teacher_user)
        url = reverse(
            "dashboard:teacher_missed_deadlines",
            kwargs={"slug": course.slug, "assignment_id": past_assignment.id},
        )
        resp = client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_past_deadline"] is True
        assert resp.context["still_open_late"] is True
        assert resp.context["total_missed_count"] == 1
        missed = list(resp.context["missed_enrollments"])
        assert len(missed) == 1
        assert missed[0].student == s_unsubmitted

    def test_idor_protection_on_nested_assignment_routes(
        self, client, teacher_user, course, user_factory
    ):
        """Accessing an assignment belonging to Course B under Course A's slug returns 404."""
        course_b = Course.objects.create(title="Course B", slug="course-b", is_published=True)
        assignment_b = Assignment.objects.create(
            course=course_b,
            title="Assignment B",
            opens_at=timezone.now(),
            due_at=timezone.now() + timedelta(days=3),
            is_published=True,
        )

        client.force_login(teacher_user)
        # Attempt to access assignment_b via course.slug
        url = reverse(
            "dashboard:teacher_course_assignment_submissions",
            kwargs={"slug": course.slug, "assignment_id": assignment_b.id},
        )
        resp = client.get(url)
        assert resp.status_code == 404

        url_missed = reverse(
            "dashboard:teacher_missed_deadlines",
            kwargs={"slug": course.slug, "assignment_id": assignment_b.id},
        )
        resp_missed = client.get(url_missed)
        assert resp_missed.status_code == 404


# ---------------------------------------------------------------------------
# 7. Mutating Endpoints Require POST
# ---------------------------------------------------------------------------
class TestMutatingEndpointsRequirePOST:
    def test_get_rejected_on_all_mutating_endpoints(
        self, client, teacher_user, student_user, course, assignment
    ):
        """Every mutating endpoint returns 405 Method Not Allowed on GET."""
        client.force_login(teacher_user)
        enrollment = Enrollment.objects.create(
            student=student_user, course=course, status=Enrollment.Status.PENDING
        )
        sub = Submission.objects.create(assignment=assignment, student=student_user)

        mutating_urls = [
            reverse("dashboard:teacher_enrollment_action", kwargs={"enrollment_id": enrollment.id}),
            reverse("dashboard:teacher_enrollments_bulk_action"),
            reverse("dashboard:teacher_enrollment_manual"),
            reverse("dashboard:teacher_submission_unlock", kwargs={"submission_id": sub.id}),
            reverse("dashboard:teacher_student_toggle_active", kwargs={"student_id": student_user.id}),
        ]

        for url in mutating_urls:
            resp = client.get(url)
            assert resp.status_code == 405, f"Expected 405 on GET {url}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# 8. Export Logging & Rate Limiting
# ---------------------------------------------------------------------------
class TestExportLoggingAndRateLimits:
    def test_export_is_logged_with_user_and_course(self, client, teacher_user, course, caplog):
        """Exporting grades or progress writes a structured log with user, course, and time."""
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_course_grades_export", kwargs={"slug": course.slug})

        with caplog.at_level(logging.INFO):
            resp = client.get(url)
            assert resp.status_code == 200

        assert any("Course grades CSV export" in r.message for r in caplog.records)
        assert any(str(teacher_user.id) in r.message for r in caplog.records)
        assert any(course.slug in r.message for r in caplog.records)

    def test_export_rate_limit(self, client, teacher_user, course):
        """Exports are rate limited (10/min) per user."""
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_course_grades_export", kwargs={"slug": course.slug})

        # 10 calls succeed
        for _ in range(10):
            resp = client.get(url)
            assert resp.status_code == 200

        # 11th call gets blocked (429 Too Many Requests)
        resp = client.get(url)
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 9. Bounded Query Counts
# ---------------------------------------------------------------------------
class TestBoundedQueryCounts:
    def test_student_directory_uses_bounded_queries(
        self, client, teacher_user, course, user_factory, django_assert_num_queries
    ):
        """Student list query count is constant and does not suffer N+1 as student volume increases."""
        # Create 10 students with enrollments and progress
        for i in range(10):
            st = user_factory(email=f"perf_st_{i}@example.com", role=User.Role.STUDENT)
            Enrollment.objects.create(student=st, course=course, status=Enrollment.Status.ACTIVE)

        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_students")

        # Query count is bounded (under 19 queries total including session, user, counts, and subqueries)
        with django_assert_num_queries(18):
            resp = client.get(url)
            assert resp.status_code == 200
            assert len(resp.context["students"]) == 10
