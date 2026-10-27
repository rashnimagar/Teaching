import re
import secrets

from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

ASCII_SLUG_REGEX = re.compile(r"^[a-z0-9-]+$")


def generate_course_slug(title: str) -> str:
    """
    Generates a URL-safe ASCII slug from the course title.
    Since Django's slugify drops Devanagari/non-ASCII characters,
    if the resulting slug is empty, falls back to 'course-<6 random hex chars>'.
    """
    slug = slugify(title)
    if not slug:
        slug = f"course-{secrets.token_hex(3)}"
    return slug


def validate_ascii_slug(value: str) -> bool:
    """
    Validates that a slug strictly contains only lowercase ASCII letters,
    numbers, and hyphens (matching Django's <slug:> URL converter).
    """
    if (
        not value
        or not ASCII_SLUG_REGEX.match(value)
        or value.startswith("-")
        or value.endswith("-")
    ):
        raise ValidationError(
            _(
                "Slug may only contain lowercase ASCII letters, numbers, and hyphens (e.g. 'django-basics')."
            )
        )
    return True
