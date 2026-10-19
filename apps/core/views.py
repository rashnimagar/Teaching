import logging

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)


def home_view(request):
    """Public home landing page."""
    return render(request, "core/home.html")


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
