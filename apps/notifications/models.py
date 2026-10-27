from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


def validate_internal_url(value: str) -> None:
    """
    Validates that a URL is strictly an internal, relative path:
    - Must start with a single '/'
    - Must not start with '//' (protocol-relative URL)
    - Must not start with '/\\'
    - Must not contain backslashes ('\\')
    - Must not contain control characters or newlines (ASCII < 32 or 127)
    """
    if not value:
        return

    # Reject ASCII control characters and newlines
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValidationError(_("URL must not contain control characters or newlines."))

    # Reject backslashes
    if "\\" in value:
        raise ValidationError(_("URL must not contain backslashes."))

    # Must start with exactly one forward slash and NOT start with // or /\\
    if not value.startswith("/") or value.startswith("//") or value.startswith("/\\"):
        raise ValidationError(_("URL must be an internal path starting with a single '/'."))


class Notification(TimeStampedModel):
    """
    In-app notification for students regarding course activity,
    assignment updates, and download permission decisions.
    """

    class Kind(models.TextChoices):
        DOWNLOAD_APPROVED = "download_approved", _("Download Approved")
        DOWNLOAD_DENIED = "download_denied", _("Download Denied")
        DOWNLOAD_REVOKED = "download_revoked", _("Download Revoked")
        ENROLLMENT_APPROVED = "enrollment_approved", _("Enrollment Approved")
        ENROLLMENT_REVOKED = "enrollment_revoked", _("Enrollment Revoked")
        SUBMISSION_GRADED = "submission_graded", _("Submission Graded")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("recipient"),
    )
    kind = models.CharField(
        _("kind"),
        max_length=32,
        choices=Kind.choices,
        db_index=True,
    )
    title = models.CharField(_("title"), max_length=255)
    body = models.TextField(
        _("body"),
        help_text=_("Plain text notification body. Always escaped when rendered in templates."),
    )
    url = models.CharField(
        _("action URL"),
        max_length=500,
        blank=True,
        validators=[validate_internal_url],
        help_text=_(
            "Internal relative URL starting with a single slash (e.g. /learn/python/materials/)."
        ),
    )
    read_at = models.DateTimeField(_("read at"), null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.recipient.email} - {self.title} ({self.get_kind_display()})"

    def clean(self) -> None:
        super().clean()
        if self.url:
            validate_internal_url(self.url)

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
