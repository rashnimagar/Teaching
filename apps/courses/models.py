import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.image_utils import generate_webp_variant
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_file


class Course(TimeStampedModel):
    """
    Core educational course offering on the platform.
    """

    title = models.CharField(_("title"), max_length=255)
    slug = models.SlugField(_("slug"), max_length=255, unique=True)
    short_description = models.CharField(_("short description"), max_length=200, blank=True)
    description = models.TextField(_("description"), blank=True)
    thumbnail = models.ImageField(
        _("thumbnail"),
        upload_to="courses/thumbnails/",
        blank=True,
        null=True,
        validators=[validate_image_file],
    )
    thumbnail_webp = models.ImageField(
        _("thumbnail (WebP variant)"),
        upload_to="courses/thumbnails/webp/",
        blank=True,
        null=True,
    )
    is_published = models.BooleanField(_("is published"), default=False, db_index=True)
    is_featured = models.BooleanField(_("is featured"), default=False, db_index=True)
    is_archived = models.BooleanField(_("is archived"), default=False, db_index=True)
    requires_approval = models.BooleanField(_("requires approval"), default=False)
    is_free = models.BooleanField(_("is free"), default=True, db_index=True)
    price = models.DecimalField(_("price"), max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(_("currency"), max_length=3, default="NPR")

    class Meta:
        verbose_name = _("course")
        verbose_name_plural = _("courses")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_published", "created_at"]),
            models.Index(fields=["is_featured", "is_published"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_free=True)
                | (Q(is_free=False) & Q(price__isnull=False) & Q(price__gt=0)),
                name="course_paid_must_have_positive_price",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if not self.is_free and (self.price is None or self.price <= 0):
            raise ValidationError({"price": _("Paid courses must specify a positive price.")})

    def save(self, *args, **kwargs):
        if self.thumbnail:
            filename, webp_file = generate_webp_variant(
                self.thumbnail, max_width=1200, max_height=800
            )
            if webp_file:
                self.thumbnail_webp.save(filename, webp_file, save=False)
        super().save(*args, **kwargs)


class Lesson(TimeStampedModel):
    """
    A sequential video lesson belonging to a course.
    """

    class VideoProvider(models.TextChoices):
        BUNNY = "bunny", _("Bunny Stream")
        VIMEO = "vimeo", _("Vimeo")
        YOUTUBE = "youtube", _("YouTube")

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lessons",
        verbose_name=_("course"),
    )
    title = models.CharField(_("title"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    order = models.PositiveIntegerField(_("order"), default=1)
    video_provider = models.CharField(
        _("video provider"),
        max_length=20,
        choices=VideoProvider.choices,
        default=VideoProvider.BUNNY,
    )
    video_id = models.CharField(_("video identifier"), max_length=255, blank=True)
    duration = models.DurationField(_("duration"), null=True, blank=True)
    is_preview = models.BooleanField(_("is preview"), default=False)
    is_published = models.BooleanField(_("is published"), default=False, db_index=True)

    class Meta:
        verbose_name = _("lesson")
        verbose_name_plural = _("lessons")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["course", "order"]),
            models.Index(fields=["course", "is_published"]),
        ]

    def __str__(self):
        return f"{self.course.title} - {self.order}. {self.title}"

    def clean(self):
        super().clean()
        if self.video_id:
            vid = self.video_id.strip()
            if self.video_provider == self.VideoProvider.YOUTUBE:
                # Standard YouTube video IDs are 11 characters alphanumeric + _ -
                if not re.match(r"^[a-zA-Z0-9_-]{11}$", vid):
                    raise ValidationError(
                        {"video_id": _("YouTube video ID must be an 11-character identifier.")}
                    )
            elif self.video_provider == self.VideoProvider.VIMEO:
                # Vimeo video IDs are typically numeric digits (or alphanumeric for showcase/player embeds)
                if not re.match(r"^[0-9a-zA-Z_-]{5,20}$", vid):
                    raise ValidationError(
                        {"video_id": _("Vimeo video identifier format is invalid.")}
                    )
            elif self.video_provider == self.VideoProvider.BUNNY:
                # Bunny Stream video IDs are typically UUIDs or alphanumeric GUIDs
                if not re.match(r"^[0-9a-fA-F-]{10,64}$", vid):
                    raise ValidationError(
                        {"video_id": _("Bunny Stream video ID must be a valid GUID/UUID.")}
                    )


class Enrollment(TimeStampedModel):
    """
    Tracks a student's enrollment status and acquisition source for a course.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        REVOKED = "revoked", _("Revoked")

    class Source(models.TextChoices):
        MANUAL = "manual", _("Manual")
        FREE = "free", _("Free Enrollment")
        PAYMENT = "payment", _("Payment")

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name=_("student"),
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,  # Prevent deleting courses that have enrollments
        related_name="enrollments",
        verbose_name=_("course"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    source = models.CharField(
        _("source"),
        max_length=20,
        choices=Source.choices,
        default=Source.FREE,
    )

    class Meta:
        verbose_name = _("enrollment")
        verbose_name_plural = _("enrollments")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["course", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_student_course_enrollment",
            ),
        ]

    def __str__(self):
        return f"{self.student.email} - {self.course.title} ({self.get_status_display()})"


class LessonProgress(TimeStampedModel):
    """
    Tracks a student's completion and playback position within a specific lesson.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
        verbose_name=_("student"),
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="progress",
        verbose_name=_("lesson"),
    )
    last_position_seconds = models.PositiveIntegerField(_("last position (seconds)"), default=0)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("lesson progress")
        verbose_name_plural = _("lesson progresses")
        indexes = [
            models.Index(fields=["student", "completed_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lesson"],
                name="unique_student_lesson_progress",
            ),
        ]

    def __str__(self):
        state = "Completed" if self.completed_at else f"In progress ({self.last_position_seconds}s)"
        return f"{self.student.email} - {self.lesson.title}: {state}"
