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
    is_published = models.BooleanField(
        _("is published"),
        default=True,
        db_index=True,
        help_text=_("Draft assignments are hidden from students until published."),
    )

    class Meta:
        verbose_name = _("assignment")
        verbose_name_plural = _("assignments")
        ordering = ["-due_at"]
        indexes = [
            models.Index(fields=["course", "is_published", "due_at"]),
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
    original_filename = models.CharField(
        _("original file name"),
        max_length=255,
        blank=True,
        help_text=_("Sanitized original filename preserved for user-facing display."),
    )
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
    is_unlocked = models.BooleanField(_("is unlocked"), default=False)

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
        # Text length validation (Requirement 12)
        max_text_len = getattr(settings, "ASSIGNMENT_MAX_TEXT_LENGTH", 20000)
        if self.content_text and len(self.content_text) > max_text_len:
            raise ValidationError(
                {
                    "content_text": _(
                        "Written response exceeds maximum length of %(max_len)s characters."
                    )
                    % {"max_len": max_text_len}
                }
            )

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

        # Requirement 1: Lock editing once a submission is graded unless unlocked
        if self.pk and self.assignment_id:
            orig = (
                Submission.objects.filter(pk=self.pk)
                .values("grade", "content_text", "file", "is_unlocked")
                .first()
            )
            was_unlocked = bool(orig and orig.get("is_unlocked"))
            is_unlocked_now = bool(self.is_unlocked)

            if orig and orig["grade"] is not None and not (was_unlocked or is_unlocked_now):
                if orig["content_text"] != self.content_text or orig["file"] != (
                    self.file.name if self.file else ""
                ):
                    raise ValidationError(
                        _("This submission has already been graded and can no longer be edited.")
                    )

            now = timezone.now()
            if now > self.assignment.due_at and not self.assignment.allow_late and not (was_unlocked or is_unlocked_now):
                raise ValidationError(
                    _(
                        "Submissions cannot be edited after the deadline because late submissions are disabled."
                    )
                )

    def save(self, *args, **kwargs):
        # With allow_late, is_late follows the latest save; submitted_at and is_late use one now() value.
        now = timezone.now()
        if not self.pk:
            if not self.submitted_at:
                self.submitted_at = now
            if self.assignment_id:
                self.is_late = self.submitted_at > self.assignment.due_at
        else:
            if self.assignment_id and self.submitted_at:
                self.is_late = self.submitted_at > self.assignment.due_at

        # Automatically record graded_at when a grade is first assigned
        if self.grade is not None and not self.graded_at:
            self.graded_at = now

        super().save(*args, **kwargs)


class SubmissionEvent(TimeStampedModel):
    """
    Audit record for submission grading and unlocking lifecycle events.
    """

    submission = models.ForeignKey(
        Submission,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name=_("submission"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submission_events",
        verbose_name=_("actor"),
    )
    action = models.CharField(_("action"), max_length=32)  # "graded", "regraded", "unlocked"
    old_grade = models.DecimalField(_("previous grade"), max_digits=5, decimal_places=2, null=True, blank=True)
    new_grade = models.DecimalField(_("new grade"), max_digits=5, decimal_places=2, null=True, blank=True)
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("submission event")
        verbose_name_plural = _("submission events")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Submission {self.submission_id} [{self.action}] by {self.actor}"


from django.db.models.signals import post_delete  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(post_delete, sender=Submission)
def cleanup_submission_file_on_delete(sender, instance, **kwargs):
    """
    Remove physical private file when a submission is deleted.
    Gracefully handles missing files without crashing (Requirement 19).
    """
    if instance.file:
        try:
            instance.file.storage.delete(instance.file.name)
        except (FileNotFoundError, OSError):
            pass
