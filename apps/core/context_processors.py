import logging

from django.conf import settings
from django.db import OperationalError, ProgrammingError

from apps.core.models import SiteSettings

logger = logging.getLogger(__name__)


def site_settings(request):
    """
    Context processor exposing the singleton SiteSettings instance to all templates.
    Leverages Django's configured shared cache (invalidated immediately on save).
    Guaranteed never to crash pages when database errors or missing tables occur.
    """
    try:
        settings_obj = SiteSettings.get_solo()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "Could not load SiteSettings from database (%s); using fallback defaults.", exc
        )
        settings_obj = SiteSettings(
            site_name="Teaching Platform",
            hero_headline="Master Skills with Structured Lessons & Timed Assignments",
            hero_subheadline="Focused, distraction-free educational courses designed to build real-world competency.",
        )

    return {
        "site_settings": settings_obj,
        "SITE_URL": getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/"),
    }
