import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assignments.models import Submission, SubmissionEvent
from apps.notifications.models import Notification
from apps.notifications.services import create_notification

logger = logging.getLogger(__name__)


def grade_submission(
    submission_id: int,
    grade: Decimal,
    feedback: str,
    teacher_user,
) -> tuple[Submission, bool, str]:
    """
    Central, race-safe grading service for Submissions.
    Used uniformly across the Teacher Dashboard and Django admin.

    Guarantees:
    - Atomicity & row locking via select_for_update()
    - Range validation: 0 <= grade <= assignment.max_score
    - Regrade rules: graded_by and graded_at change ONLY when the grade changes
    - Student notification dispatched ONLY when the grade changes
    - Notification failure never blocks or fails the transaction
    - Audit log written to SubmissionEvent
    """
    with transaction.atomic():
        try:
            submission = (
                Submission.objects.select_for_update()
                .select_related("assignment", "assignment__course", "student")
                .get(pk=submission_id)
            )
        except Submission.DoesNotExist:
            return None, False, _("Submission not found.")

        # Validate score bounds
        max_score = submission.assignment.max_score
        if grade < Decimal("0"):
            raise ValidationError(_("Grade cannot be negative."))
        if grade > max_score:
            raise ValidationError(
                _("Grade (%(grade)s) cannot exceed the assignment maximum score of %(max)s.")
                % {"grade": grade, "max": max_score}
            )

        old_grade = submission.grade
        grade_changed = (old_grade != grade)
        is_first_grade = (old_grade is None)

        action_name = "graded" if is_first_grade else ("regraded" if grade_changed else "feedback_updated")

        submission.feedback = feedback.strip()

        if grade_changed:
            submission.grade = grade
            submission.graded_by = teacher_user
            submission.graded_at = timezone.now()

        # If unlocked, grading locks it back
        submission.is_unlocked = False
        submission.save()

        # Record audit event
        SubmissionEvent.objects.create(
            submission=submission,
            actor=teacher_user,
            action=action_name,
            old_grade=old_grade,
            new_grade=submission.grade,
            note=feedback.strip()[:200] if feedback else "",
        )

        logger.info(
            "Teacher %s %s submission %s (student: %s, assignment: %s) with grade %s (was: %s)",
            getattr(teacher_user, "id", None),
            action_name,
            submission.id,
            submission.student_id,
            submission.assignment_id,
            submission.grade,
            old_grade,
        )

        # Notify student ONLY if grade changed or first graded (Requirement 6)
        if grade_changed:
            student = submission.student
            assign = submission.assignment
            grade_val = submission.grade
            max_val = assign.max_score
            course_slug = assign.course.slug
            assign_id = assign.id
            assign_title = assign.title

            def send_grade_notification():
                try:
                    create_notification(
                        recipient=student,
                        kind=Notification.Kind.SUBMISSION_GRADED,
                        title=str(_("Assignment Graded: %(title)s") % {"title": assign_title}),
                        body=str(_(
                            "Your submission for '%(title)s' has been graded: %(grade)s/%(max)s."
                        ) % {"title": assign_title, "grade": grade_val, "max": max_val}),
                        url=f"/courses/{course_slug}/assignments/{assign_id}/",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Failed to send grade notification for student %s on assignment %s: %s",
                        student.id,
                        assign_id,
                        exc,
                    )

            transaction.on_commit(send_grade_notification)

        msg = (
            _("Submission graded successfully (%(grade)s / %(max)s).")
            % {"grade": submission.grade, "max": max_score}
            if grade_changed
            else _("Feedback updated successfully.")
        )
        return submission, True, msg


def unlock_submission(
    submission_id: int,
    teacher_user,
    note: str = "",
) -> tuple[Submission, bool, str]:
    """
    Unlocks a previously submitted assignment, allowing the student to edit
    and resubmit their work while preserving submission history.
    """
    with transaction.atomic():
        try:
            submission = (
                Submission.objects.select_for_update()
                .select_related("assignment", "student")
                .get(pk=submission_id)
            )
        except Submission.DoesNotExist:
            return None, False, _("Submission not found.")

        submission.is_unlocked = True
        submission.save(update_fields=["is_unlocked", "updated_at"])

        SubmissionEvent.objects.create(
            submission=submission,
            actor=teacher_user,
            action="unlocked",
            old_grade=submission.grade,
            new_grade=submission.grade,
            note=note or _("Submission unlocked for student revision."),
        )

        logger.info(
            "Teacher %s unlocked submission %s for student %s",
            getattr(teacher_user, "id", None),
            submission.id,
            submission.student_id,
        )

        return submission, True, _("Submission has been unlocked. The student may now resubmit.")
