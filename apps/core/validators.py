from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image_file(file) -> None:
    """
    Validate that an uploaded image:
    1. Does not exceed 5 MB in size.
    2. Has a valid image file extension (jpg, jpeg, png, webp).
    3. Is verified by Pillow to be a genuine, uncorrupted image.
    """
    if not file:
        return

    # Check file size
    if file.size > MAX_IMAGE_SIZE_BYTES:
        max_mb = MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(
            _("Image size exceeds %(max_mb)s MB limit."),
            params={"max_mb": max_mb},
        )

    # Check extension
    ext = Path(file.name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            _("Image extension '.%(ext)s' is not supported. Allowed: JPG, PNG, WebP."),
            params={"ext": ext},
        )

    # Verify image with Pillow
    try:
        # Save position to rewind after reading
        initial_pos = file.tell() if hasattr(file, "tell") else 0
        img = Image.open(file)
        img.verify()
        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValidationError(
                _("Unsupported image format '%(fmt)s'."),
                params={"fmt": img.format},
            )
        if hasattr(file, "seek"):
            file.seek(initial_pos)
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(_("Uploaded file is not a valid or supported image.")) from exc
