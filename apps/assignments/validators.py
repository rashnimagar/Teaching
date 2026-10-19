import os
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

ALLOWED_EXTENSIONS = {
    "pdf",
    "zip",
    "tar",
    "gz",
    "py",
    "ipynb",
    "docx",
    "doc",
    "txt",
    "png",
    "jpg",
    "jpeg",
}

DISALLOWED_MIME_PREFIXES = (
    "application/x-dosexec",
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-msdos-program",
)


def submission_file_path(instance, filename: str) -> str:
    """
    Generate an unguessable randomized file path within the private storage.
    """
    ext = Path(filename).suffix.lower()
    random_filename = f"{uuid.uuid4().hex}{ext}"
    return os.path.join("submissions", random_filename)


def validate_submission_file(file) -> None:
    """
    Validate submission file size, extension, and content type.
    """
    if not file:
        return

    # Check file size
    if file.size > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(
            _("File size exceeds %(max_mb)s MB limit."),
            params={"max_mb": max_mb},
        )

    # Check extension
    ext = Path(file.name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            _("File extension '.%(ext)s' is not supported."),
            params={"ext": ext},
        )

    # Check content type if present
    content_type = getattr(file, "content_type", "")
    if content_type:
        for disallowed in DISALLOWED_MIME_PREFIXES:
            if content_type.startswith(disallowed):
                raise ValidationError(_("Executable files are strictly forbidden."))
