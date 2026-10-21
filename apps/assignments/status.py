"""
Pure status calculation for assignments and student submissions.
Calculated dynamically from timestamps and assignment constraints, never stored in the database.
"""

from dataclasses import dataclass
from datetime import datetime

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AssignmentStatusCode(models.TextChoices):
    NOT_OPEN = "not_open", _("Not Open Yet")
    OPEN = "open", _("Open")
    SUBMITTED = "submitted", _("Submitted")
    LATE = "late", _("Late Submission")
    OVERDUE_LATE_ALLOWED = "overdue_late_allowed", _("Overdue (Late Allowed)")
    MISSED = "missed", _("Missed")
    GRADED = "graded", _("Graded")


@dataclass(frozen=True)
class AssignmentStatusInfo:
    code: str
    label: str
    badge_variant: str
    is_actionable: bool
    is_graded: bool
    is_submitted: bool


def get_assignment_status(
    assignment, submission=None, now: datetime | None = None
) -> AssignmentStatusInfo:
    """
    Computes the exact status of an assignment for a given student submission and reference time.

    Precedence:
    1. Graded: submission exists and grade is assigned.
    2. Submitted on-time: submission exists and is_late is False.
    3. Late submission: submission exists and is_late is True.
    4. Not open yet: now < opens_at.
    5. Open: opens_at <= now <= due_at (unsubmitted).
    6. Overdue (Late Allowed): now > due_at, unsubmitted, allow_late is True.
    7. Missed: now > due_at, unsubmitted, allow_late is False.
    """
    if now is None:
        now = timezone.now()

    # 1. Graded
    if submission is not None and submission.grade is not None:
        grade = submission.grade
        try:
            formatted_grade = f"{int(grade)}" if grade == int(grade) else f"{grade:.2f}"
        except (ValueError, TypeError):
            formatted_grade = str(grade)

        return AssignmentStatusInfo(
            code=AssignmentStatusCode.GRADED,
            label=f"Graded: {formatted_grade}/{assignment.max_score} pts",
            badge_variant="success",
            is_actionable=False,  # Graded submissions cannot be edited
            is_graded=True,
            is_submitted=True,
        )

    # 2. Submitted on-time
    if submission is not None and not submission.is_late:
        can_edit = now <= assignment.due_at or assignment.allow_late
        return AssignmentStatusInfo(
            code=AssignmentStatusCode.SUBMITTED,
            label="Submitted",
            badge_variant="success",
            is_actionable=can_edit,
            is_graded=False,
            is_submitted=True,
        )

    # 3. Submitted late
    if submission is not None and submission.is_late:
        can_edit = assignment.allow_late
        return AssignmentStatusInfo(
            code=AssignmentStatusCode.LATE,
            label="Late Submission",
            badge_variant="warning",
            is_actionable=can_edit,
            is_graded=False,
            is_submitted=True,
        )

    # 4. Not open yet
    if now < assignment.opens_at:
        return AssignmentStatusInfo(
            code=AssignmentStatusCode.NOT_OPEN,
            label="Not Open Yet",
            badge_variant="neutral",
            is_actionable=False,
            is_graded=False,
            is_submitted=False,
        )

    # 5. Open for on-time submission
    if now <= assignment.due_at:
        return AssignmentStatusInfo(
            code=AssignmentStatusCode.OPEN,
            label="Open",
            badge_variant="brand",
            is_actionable=True,
            is_graded=False,
            is_submitted=False,
        )

    # 6. Overdue but late submissions are allowed
    if assignment.allow_late:
        return AssignmentStatusInfo(
            code=AssignmentStatusCode.OVERDUE_LATE_ALLOWED,
            label="Overdue (Late Allowed)",
            badge_variant="warning",
            is_actionable=True,
            is_graded=False,
            is_submitted=False,
        )

    # 7. Missed: past due and late submissions forbidden
    return AssignmentStatusInfo(
        code=AssignmentStatusCode.MISSED,
        label="Missed",
        badge_variant="danger",
        is_actionable=False,
        is_graded=False,
        is_submitted=False,
    )
