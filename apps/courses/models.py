import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assignments.validators import sanitize_display_filename
from apps.core.image_utils import generate_webp_variant
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_file
from apps.courses.validators_materials import (
    VIEW_ONLY_ALLOWED_EXTENSIONS,
    material_file_path,
    validate_material_file,
)


def get_private_storage():
    """Callable returning the configured private storage backend."""
    return storages["private"]


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
        old_thumbnail = None
        old_webp = None
        if self.pk:
            try:
                old_inst = Course.objects.get(pk=self.pk)
                if old_inst.thumbnail and old_inst.thumbnail != self.thumbnail:
                    old_thumbnail = old_inst.thumbnail.name
                if old_inst.thumbnail_webp and (
                    old_inst.thumbnail != self.thumbnail or not self.thumbnail
                ):
                    old_webp = old_inst.thumbnail_webp.name
            except Course.DoesNotExist:
                pass

        if self.thumbnail and (not self.pk or old_thumbnail):
            filename, webp_file = generate_webp_variant(
                self.thumbnail, max_width=1200, max_height=800
            )
            if webp_file:
                self.thumbnail_webp.save(filename, webp_file, save=False)
        elif not self.thumbnail:
            self.thumbnail_webp = None

        super().save(*args, **kwargs)

        if old_thumbnail or old_webp:
            from django.core.files.storage import default_storage

            def _cleanup():
                if old_thumbnail:
                    try:
                        default_storage.delete(old_thumbnail)
                    except (FileNotFoundError, OSError):
                        pass
                if old_webp:
                    try:
                        default_storage.delete(old_webp)
                    except (FileNotFoundError, OSError):
                        pass

            transaction.on_commit(_cleanup)


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
    video_id = models.CharField(
        _("video identifier"),
        max_length=255,
        blank=True,
        help_text=_(
            "Videos from other channels may have embedding disabled. Check Share > Embed on YouTube."
        ),
    )
    video_hash = models.CharField(
        _("video privacy hash"),
        max_length=64,
        blank=True,
        help_text=_("Optional security hash for unlisted/private Vimeo videos."),
    )
    duration = models.DurationField(_("duration"), null=True, blank=True)
    is_preview = models.BooleanField(
        _("is preview"),
        default=False,
        help_text=_("Preview lessons can be watched by any logged-in user."),
    )
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
            from apps.courses.services.video import extract_video_info

            extracted = extract_video_info(self.video_id, self.video_provider)
            if extracted["video_id"] != self.video_id:
                self.video_id = extracted["video_id"]
            if extracted.get("provider"):
                self.video_provider = extracted["provider"]
            if extracted.get("video_hash") and not self.video_hash:
                self.video_hash = extracted["video_hash"]

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

        if self.video_hash:
            vhash = self.video_hash.strip()
            if not re.match(r"^[0-9a-zA-Z_-]{6,64}$", vhash):
                raise ValidationError(
                    {"video_hash": _("Vimeo video privacy hash must be an alphanumeric string.")}
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


class EnrollmentEvent(TimeStampedModel):
    """
    Audit record for enrollment status transitions, capturing actor,
    status change, and optional notes.
    """

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name=_("enrollment"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enrollment_events",
        verbose_name=_("actor"),
    )
    from_status = models.CharField(_("from status"), max_length=20)
    to_status = models.CharField(_("to status"), max_length=20)
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("enrollment event")
        verbose_name_plural = _("enrollment events")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Enrollment {self.enrollment_id}: {self.from_status} -> {self.to_status} by {self.actor}"


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


class CourseMaterial(TimeStampedModel):
    """
    A post or collection of downloadable/viewable educational materials for a course.
    """

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="materials",
        verbose_name=_("course"),
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="materials",
        verbose_name=_("lesson"),
    )
    title = models.CharField(_("title"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    order = models.PositiveIntegerField(_("order"), default=1)
    is_published = models.BooleanField(_("is published"), default=True, db_index=True)
    is_archived = models.BooleanField(_("is archived"), default=False, db_index=True)

    class Meta:
        verbose_name = _("course material")
        verbose_name_plural = _("course materials")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["course", "is_published", "is_archived"]),
            models.Index(fields=["lesson", "is_published"]),
        ]

    def __str__(self):
        return f"{self.course.title} - {self.title}"

    def clean(self):
        super().clean()
        if self.lesson_id and self.lesson.course_id != self.course_id:
            raise ValidationError(
                {"lesson": _("The linked lesson must belong to the same course as the material.")}
            )


class MaterialItem(TimeStampedModel):
    """
    An individual item inside a CourseMaterial post: private file, external link, or embedded video.
    """

    class ItemType(models.TextChoices):
        FILE = "file", _("File")
        LINK = "link", _("Link")
        VIDEO = "video", _("Video")

    class DownloadPolicy(models.TextChoices):
        REQUEST_REQUIRED = "request_required", _("Request Required")
        OPEN_TO_ENROLLED = "open_to_enrolled", _("Open to Enrolled Students")
        VIEW_ONLY = "view_only", _("View Only (In-browser preview only)")

    material = models.ForeignKey(
        CourseMaterial,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name=_("material"),
    )
    title = models.CharField(_("title"), max_length=255)
    item_type = models.CharField(
        _("item type"),
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.FILE,
        db_index=True,
    )

    # File fields (item_type == 'file')
    file = models.FileField(
        _("file"),
        storage=get_private_storage,
        upload_to=material_file_path,
        validators=[validate_material_file],
        blank=True,
        null=True,
    )
    original_filename = models.CharField(_("original filename"), max_length=255, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(_("file size (bytes)"), default=0)
    download_policy = models.CharField(
        _("download policy"),
        max_length=20,
        choices=DownloadPolicy.choices,
        default=DownloadPolicy.REQUEST_REQUIRED,
    )

    # Link fields (item_type == 'link')
    external_url = models.URLField(_("external URL"), max_length=1000, blank=True)

    # Video fields (item_type == 'video')
    video_provider = models.CharField(
        _("video provider"),
        max_length=20,
        choices=Lesson.VideoProvider.choices,
        default=Lesson.VideoProvider.BUNNY,
        blank=True,
    )
    video_id = models.CharField(_("video identifier"), max_length=255, blank=True)
    video_hash = models.CharField(_("video privacy hash"), max_length=64, blank=True)

    order = models.PositiveIntegerField(_("order"), default=1)

    class Meta:
        verbose_name = _("material item")
        verbose_name_plural = _("material items")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["material", "order"]),
            models.Index(fields=["item_type"]),
        ]

    def __str__(self):
        return f"{self.material.title} - {self.title} ({self.get_item_type_display()})"

    @property
    def file_extension(self) -> str:
        name = self.original_filename or (self.file.name if self.file else "")
        return os.path.splitext(name)[1].lower().lstrip(".")

    @property
    def is_pdf(self) -> bool:
        return self.file_extension == "pdf"

    @property
    def is_image(self) -> bool:
        return self.file_extension in {"png", "jpg", "jpeg"}

    def clean(self):
        super().clean()
        if self.item_type == self.ItemType.FILE:
            if not self.file and not self.pk:
                raise ValidationError({"file": _("A file is required for file items.")})
            if self.download_policy == self.DownloadPolicy.VIEW_ONLY:
                ext = self.file_extension
                if not ext and self.file:
                    ext = os.path.splitext(self.file.name)[1].lower().lstrip(".")
                if ext and ext not in VIEW_ONLY_ALLOWED_EXTENSIONS:
                    raise ValidationError(
                        {"download_policy": _("View-only policy is strictly restricted to PDF documents and image files (PNG, JPG).")}
                    )
        elif self.item_type == self.ItemType.LINK:
            if not self.external_url:
                raise ValidationError({"external_url": _("External URL is required for link items.")})
            if not (self.external_url.startswith("http://") or self.external_url.startswith("https://")):
                raise ValidationError({"external_url": _("URL must start with http:// or https://.")})
        elif self.item_type == self.ItemType.VIDEO:
            if not self.video_id:
                raise ValidationError({"video_id": _("Video identifier is required for video items.")})
            from apps.courses.services.video import extract_video_info

            extracted = extract_video_info(self.video_id, self.video_provider)
            if extracted["video_id"] != self.video_id:
                self.video_id = extracted["video_id"]
            if extracted.get("provider"):
                self.video_provider = extracted["provider"]
            if extracted.get("video_hash") and not self.video_hash:
                self.video_hash = extracted["video_hash"]

            vid = self.video_id.strip()
            if self.video_provider == Lesson.VideoProvider.YOUTUBE and not re.match(
                r"^[a-zA-Z0-9_-]{11}$", vid
            ):
                raise ValidationError(
                    {"video_id": _("YouTube video ID must be an 11-character identifier.")}
                )
            elif self.video_provider == Lesson.VideoProvider.VIMEO and not re.match(
                r"^[0-9a-zA-Z_-]{5,20}$", vid
            ):
                raise ValidationError(
                    {"video_id": _("Vimeo video identifier format is invalid.")}
                )
            elif self.video_provider == Lesson.VideoProvider.BUNNY and not re.match(
                r"^[0-9a-fA-F-]{10,64}$", vid
            ):
                raise ValidationError(
                    {"video_id": _("Bunny Stream video ID must be a valid GUID/UUID.")}
                )

    def save(self, *args, **kwargs):
        old_file_name = None
        old_storage = None
        if self.pk:
            try:
                old_inst = MaterialItem.objects.get(pk=self.pk)
                if old_inst.file and old_inst.file != self.file:
                    old_file_name = old_inst.file.name
                    old_storage = old_inst.file.storage
            except MaterialItem.DoesNotExist:
                pass

        if self.file and not self.original_filename:
            self.original_filename = sanitize_display_filename(os.path.basename(self.file.name))
        if self.file:
            try:
                self.file_size_bytes = self.file.size
            except (OSError, ValueError):
                pass

        super().save(*args, **kwargs)

        # Clean up replaced old file after transaction commits
        if old_file_name and old_storage:
            def _clean_old(storage=old_storage, name=old_file_name):
                try:
                    if storage.exists(name):
                        storage.delete(name)
                except Exception:
                    pass
            transaction.on_commit(_clean_old)


@receiver(post_delete, sender=MaterialItem)
def cleanup_material_file_on_delete(sender, instance, **kwargs):
    """Deletes physical file from private storage when MaterialItem is deleted."""
    if instance.file and instance.file.name:
        storage = instance.file.storage
        name = instance.file.name

        def _delete_file():
            try:
                if storage.exists(name):
                    storage.delete(name)
            except Exception:
                pass

        transaction.on_commit(_delete_file)


class DownloadRequest(TimeStampedModel):
    """
    Tracks a student's download access request for a specific MaterialItem.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        DENIED = "denied", _("Denied")
        REVOKED = "revoked", _("Revoked")

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="download_requests",
        verbose_name=_("student"),
    )
    material_item = models.ForeignKey(
        MaterialItem,
        on_delete=models.PROTECT,
        related_name="download_requests",
        verbose_name=_("material item"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    requested_at = models.DateTimeField(_("requested at"), default=timezone.now, db_index=True)
    decided_at = models.DateTimeField(_("decided at"), null=True, blank=True, db_index=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_download_requests",
        verbose_name=_("decided by"),
    )
    expires_at = models.DateTimeField(_("expires at"), null=True, blank=True)
    teacher_note = models.TextField(_("teacher note"), blank=True)

    class Meta:
        verbose_name = _("download request")
        verbose_name_plural = _("download requests")
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["material_item", "status"]),
            models.Index(fields=["student", "status"]),
            models.Index(fields=["status", "requested_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "material_item"],
                condition=Q(status__in=["pending", "approved"]),
                name="unique_pending_or_approved_download_request",
            ),
        ]

    def __str__(self):
        return f"{self.student.email} - {self.material_item.title} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return bool(
            self.status == self.Status.APPROVED
            and self.expires_at
            and self.expires_at <= timezone.now()
        )

    @property
    def computed_status(self) -> str:
        if self.is_expired:
            return "expired"
        return self.status


class DownloadLog(TimeStampedModel):
    """
    Audit record logging student material downloads, tracking IP and timestamp.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="download_logs",
        verbose_name=_("student"),
    )
    material_item = models.ForeignKey(
        MaterialItem,
        on_delete=models.CASCADE,
        related_name="download_logs",
        verbose_name=_("material item"),
    )
    downloaded_at = models.DateTimeField(_("downloaded at"), default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)

    class Meta:
        verbose_name = _("download log")
        verbose_name_plural = _("download logs")
        ordering = ["-downloaded_at"]
        indexes = [
            models.Index(fields=["material_item", "downloaded_at"]),
            models.Index(fields=["student", "downloaded_at"]),
        ]

    def __str__(self):
        return f"{self.student.email} downloaded {self.material_item.title} at {self.downloaded_at}"
