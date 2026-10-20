import logging

from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.models import FAQItem, SiteSettings
from apps.core.utils import serialize_json_ld
from apps.courses.models import Course

logger = logging.getLogger(__name__)


def home_view(request):
    """
    Public home landing page.
    Renders hero, available courses grid, instructor bio (if filled), how it works, and FAQs.
    """
    site_settings = SiteSettings.get_solo()

    featured_courses = (
        Course.objects.filter(is_published=True, is_archived=False)
        .annotate(
            lesson_count=Count("lessons", filter=Q(lessons__is_published=True), distinct=True)
        )
        .order_by("-is_featured", "-created_at")[:6]
    )

    faqs = FAQItem.objects.filter(is_published=True).order_by("order", "id")

    # Generate EducationalOrganization Schema.org JSON-LD
    org_schema = {
        "@context": "https://schema.org",
        "@type": "EducationalOrganization",
        "name": site_settings.site_name,
        "url": settings.SITE_URL,
        "description": site_settings.hero_subheadline,
    }
    if site_settings.contact_email:
        org_schema["email"] = site_settings.contact_email

    json_ld_raw = serialize_json_ld(org_schema)

    context = {
        "featured_courses": featured_courses,
        "faqs": faqs,
        "json_ld_raw": json_ld_raw,
    }
    return render(request, "core/home.html", context)


def robots_txt_view(request):
    """
    Serves plain-text robots.txt disallowing sensitive private paths and pointing to sitemap.
    """
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/",
        "",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def privacy_view(request):
    """Static Privacy Policy page."""
    return render(request, "core/privacy.html")


def terms_view(request):
    """Static Terms of Service page."""
    return render(request, "core/terms.html")


def health_check_view(request):
    """
    Health check endpoint returning HTTP 200 when the application
    and connected database are operational.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_healthy = True
    except Exception as exc:
        logger.error(f"Health check database failure: {exc}")
        return JsonResponse(
            {
                "status": "error",
                "database": "unhealthy",
                "error": str(exc),
                "timestamp": timezone.now().isoformat(),
            },
            status=503,
        )

    return JsonResponse(
        {
            "status": "ok",
            "database": "healthy" if db_healthy else "unhealthy",
            "timestamp": timezone.now().isoformat(),
        },
        status=200,
    )


def handler403(request, exception=None):
    """Custom 403 Forbidden error view."""
    return render(request, "403.html", status=403)


def handler404(request, exception=None):
    """Custom 404 Not Found error view."""
    return render(request, "404.html", status=404)


def handler500(request):
    """Custom 500 Internal Server Error view."""
    return render(request, "500.html", status=500)
