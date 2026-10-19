from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assignments.validators import submission_file_path, validate_submission_file
from apps.core.models import TimeStampedModel


def get_private_storage():
    """Callable returning the configured private storage backend."""
    return storages["private"]


class Assignment(TimeStampedModel):
    """
    An assignment tied to a course and optionally to an individual lesson.
    """

    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name=_("course"),
    )
    lesson = models.ForeignKey(
        "courses.Lesson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
        verbose_name=_("lesson"),
    )
    title = models.CharField(_("title"), max_length=255)
    instructions = models.TextField(_("instructions"))
    opens_at = models.DateTimeField(_("opens at"))
    due_at = models.DateTimeField(_("due at"))
    max_score = models.PositiveIntegerField(_("maximum score"), default=100)
    allow_late = models.BooleanField(
        _("allow late submissions"),
        default=False,
        help_text=_(
            "If checked, submissions after the deadline will be accepted but flagged as late."
        ),
    )

    class Meta:
        verbose_name = _("assignment")
        verbose_name_plural = _("assignments")
        ordering = ["-due_at"]
        indexes = [
            models.Index(fields=["course", "due_at"]),
            models.Index(fields=["due_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(due_at__gt=F("opens_at")),
                name="assignment_due_after_opens",
            ),
        ]

    def __str__(self):
        return f"{self.course.title}: {self.title}"

    @property
    def is_open(self) -> bool:
        now = timezone.now()
        return self.opens_at <= now <= self.due_at

    @property
    def is_closed(self) -> bool:
        return timezone.now() > self.due_at

    def clean(self):
        super().clean()
        if self.opens_at and self.due_at and self.due_at <= self.opens_at:
            raise ValidationError(
                {"due_at": _("Due date must be strictly after the opening date.")}
            )

        if self.lesson_id and self.lesson.course_id != self.course_id:
            raise ValidationError(
                {
                    "lesson": _(
                        "The selected lesson must belong to the same course as the assignment."
                    )
                }
            )


class Submission(TimeStampedModel):
    """
    A student's submission for an assignment, supporting text, private files, and grading.
    """

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.PROTECT,  # Prevent deleting assignments that have existing submissions
        related_name="submissions",
        verbose_name=_("assignment"),
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submissions",
        verbose_name=_("student"),
    )
    content_text = models.TextField(_("written response"), blank=True)
    file = models.FileField(
        _("attached file"),
        storage=get_private_storage,
        upload_to=submission_file_path,
        validators=[validate_submission_file],
        blank=True,
        null=True,
    )
    submitted_at = models.DateTimeField(_("submitted at"), default=timezone.now)
    is_late = models.BooleanField(_("is late"), default=False)
    grade = models.DecimalField(_("grade"), max_digits=5, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(_("teacher feedback"), blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graded_submissions",
        verbose_name=_("graded by"),
    )
    graded_at = models.DateTimeField(_("graded at"), null=True, blank=True)

    class Meta:
        verbose_name = _("submission")
        verbose_name_plural = _("submissions")
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["student", "submitted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"],
                name="unique_assignment_student_submission",
            ),
            models.CheckConstraint(
                condition=Q(grade__isnull=True) | Q(grade__gte=0),
                name="submission_grade_non_negative",
            ),
        ]

    def __str__(self):
        late_indicator = " [LATE]" if self.is_late else ""
        return f"{self.assignment.title} - {self.student.email}{late_indicator}"

    def clean(self):
        super().clean()
        # Enforce that either written text or an uploaded file is supplied
        if not self.content_text.strip() and not self.file:
            raise ValidationError(
                _("You must provide either a written response or an attached file.")
            )

        # Enforce grade bounds against assignment max score
        if self.grade is not None:
            if self.grade < 0:
                raise ValidationError({"grade": _("Grade cannot be negative.")})
            if self.assignment_id and self.grade > self.assignment.max_score:
                raise ValidationError(
                    {
                        "grade": _(
                            f"Grade cannot exceed maximum score of {self.assignment.max_score}."
                        )
                    }
                )

        # Enforce editing rules: students may edit until the deadline or if late is allowed
        if self.pk and self.assignment_id:
            now = timezone.now()
            if now > self.assignment.due_at and not self.assignment.allow_late:
                raise ValidationError(
                    _(
                        "Submissions cannot be edited after the deadline because late submissions are disabled."
                    )
                )

    def save(self, *args, **kwargs):
        # Compute is_late from the same timestamp used for submitted_at
        if not self.pk:
            if not self.submitted_at:
                self.submitted_at = timezone.now()
            if self.assignment_id:
                self.is_late = self.submitted_at > self.assignment.due_at

        # Automatically record graded_at when a grade is first assigned
        if self.grade is not None and not self.graded_at:
            self.graded_at = timezone.now()

        super().save(*args, **kwargs)
