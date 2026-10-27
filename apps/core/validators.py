import re
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
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


def validate_safe_url(value: str, max_length: int = 1000) -> str:
    """
    Validates that a URL:
    - Is within max_length
    - Contains no whitespace or control characters
    - Contains no embedded credentials (e.g., http://user:pass@host)
    - Conforms to URLValidator with allowed schemes 'http' and 'https'
    """
    if not value or not isinstance(value, str):
        raise ValidationError(_("A valid URL is required."))

    # Check for whitespace or ASCII control characters
    if re.search(r"[\s\x00-\x1f\x7f]", value):
        raise ValidationError(_("URL must not contain whitespace or control characters."))

    if len(value) > max_length:
        raise ValidationError(
            _("URL exceeds the maximum length of %(max_len)s characters."),
            params={"max_len": max_length},
        )

    # Parse and inspect components
    try:
        parsed = urlsplit(value)
    except Exception as exc:
        raise ValidationError(_("Malformed URL.")) from exc

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValidationError(_("URL must start with http:// or https://."))

    if not parsed.netloc:
        raise ValidationError(_("URL must have a valid domain or host."))

    # Disallow embedded credentials (user:pass@host)
    if parsed.username or parsed.password:
        raise ValidationError(_("URLs with embedded credentials are not permitted."))

    # Validate using Django's URLValidator
    url_validator = URLValidator(schemes=["http", "https"])
    try:
        url_validator(value)
    except ValidationError:
        raise ValidationError(_("Enter a valid URL (http:// or https://).")) from None

    return value
