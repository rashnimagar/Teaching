from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Lesson

User = get_user_model()


@pytest.fixture
def course(db):
    return Course.objects.create(
        title="Django Masterclass",
        slug="django-masterclass",
        is_free=True,
    )


@pytest.fixture
def other_course(db):
    return Course.objects.create(
        title="React Masterclass",
        slug="react-masterclass",
        is_free=True,
    )


@pytest.fixture
def assignment(db, course):
    now = timezone.now()
    return Assignment.objects.create(
        course=course,
        title="Project 1",
        instructions="Complete the project.",
        opens_at=now - timedelta(days=2),
        due_at=now + timedelta(days=5),
        max_score=100,
        allow_late=False,
    )


@pytest.mark.django_db
class TestAssignmentModel:
    def test_due_date_must_be_after_opens_date_db_constraint(self, db, course):
        now = timezone.now()
        with pytest.raises(IntegrityError):
            Assignment.objects.create(
                course=course,
                title="Invalid Assignment",
                instructions="Test",
                opens_at=now,
                due_at=now - timedelta(days=1),
            )

    def test_assignment_clean_validates_due_after_opens(self, course):
        now = timezone.now()
        assignment = Assignment(
            course=course,
            title="Invalid Assignment",
            instructions="Test",
            opens_at=now,
            due_at=now - timedelta(minutes=10),
        )
        with pytest.raises(
            ValidationError, match="Due date must be strictly after the opening date."
        ):
            assignment.clean()

    def test_assignment_clean_validates_lesson_belongs_to_same_course(self, course, other_course):
        # Lesson from other_course
        foreign_lesson = Lesson.objects.create(
            course=other_course,
            title="Foreign Lesson",
            order=1,
        )
        now = timezone.now()
        assignment = Assignment(
            course=course,
            lesson=foreign_lesson,
            title="Mismatched Assignment",
            instructions="Test",
            opens_at=now,
            due_at=now + timedelta(days=1),
        )
        with pytest.raises(
            ValidationError,
            match="The selected lesson must belong to the same course as the assignment.",
        ):
            assignment.clean()


@pytest.mark.django_db
class TestSubmissionModel:
    def test_submission_uniqueness_per_student_and_assignment(self, user_factory, assignment):
        student = user_factory()
        Submission.objects.create(
            assignment=assignment,
            student=student,
            content_text="First answer",
        )
        with pytest.raises(IntegrityError):
            Submission.objects.create(
                assignment=assignment,
                student=student,
                content_text="Duplicate answer",
            )

    def test_cannot_delete_assignment_with_submissions(self, user_factory, assignment):
        student = user_factory()
        Submission.objects.create(
            assignment=assignment,
            student=student,
            content_text="My answer",
        )
        with pytest.raises(ProtectedError):
            assignment.delete()

    def test_submission_requires_content_text_or_file(self, user_factory, assignment):
        student = user_factory()
        sub = Submission(
            assignment=assignment,
            student=student,
            content_text="   ",
            file=None,
        )
        with pytest.raises(
            ValidationError,
            match="You must provide either a written response or an attached file.",
        ):
            sub.clean()

    def test_submission_grade_bounds_validation(self, user_factory, assignment):
        student = user_factory()
        # Grade exceeds max_score (100)
        sub_high = Submission(
            assignment=assignment,
            student=student,
            content_text="Answer",
            grade=Decimal("105.00"),
        )
        with pytest.raises(ValidationError, match="Grade cannot exceed maximum score of 100."):
            sub_high.clean()

        # Negative grade
        sub_low = Submission(
            assignment=assignment,
            student=student,
            content_text="Answer",
            grade=Decimal("-5.00"),
        )
        with pytest.raises(ValidationError, match="Grade cannot be negative."):
            sub_low.clean()

    def test_is_late_calculation_on_time_submission(self, user_factory, assignment):
        student = user_factory()
        # Submitted 1 hour before due date
        sub = Submission.objects.create(
            assignment=assignment,
            student=student,
            content_text="On time submission",
            submitted_at=assignment.due_at - timedelta(hours=1),
        )
        assert sub.is_late is False

    def test_is_late_calculation_late_submission(self, user_factory, assignment):
        student = user_factory()
        # Submitted 1 hour after due date
        sub = Submission.objects.create(
            assignment=assignment,
            student=student,
            content_text="Late submission",
            submitted_at=assignment.due_at + timedelta(hours=1),
        )
        assert sub.is_late is True

    def test_editing_submission_after_deadline_raises_validation_error_when_late_not_allowed(
        self, user_factory, course
    ):
        now = timezone.now()
        past_assignment = Assignment.objects.create(
            course=course,
            title="Past Assignment",
            instructions="Do this",
            opens_at=now - timedelta(days=10),
            due_at=now - timedelta(days=2),
            allow_late=False,
        )
        student = user_factory()
        sub = Submission.objects.create(
            assignment=past_assignment,
            student=student,
            content_text="Original text",
            submitted_at=past_assignment.due_at - timedelta(days=1),
        )

        # Attempt to edit after deadline has passed
        sub.content_text = "Attempted edit after deadline"
        with pytest.raises(
            ValidationError,
            match="Submissions cannot be edited after the deadline because late submissions are disabled.",
        ):
            sub.clean()
