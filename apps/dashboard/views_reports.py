import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.accounts.permissions import teacher_required
from apps.courses.models import Course
from apps.dashboard.reports import (
    stream_course_grades_csv,
    stream_course_progress_csv,
)

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET"])
@ratelimit(key="user", rate="10/m", block=True)
def teacher_course_grades_export_view(request, slug: str):
    """
    Exports per-course grades CSV (rate limited 10/min per user, logged).
    Columns: Student Name, Email, published assignments scores, total points earned / max points.
    """
    course = get_object_or_404(Course, slug=slug)
    logger.info(
        "Course grades CSV export: user_id=%s, course_slug=%s, timestamp=%s",
        request.user.id,
        course.slug,
        timezone.now().isoformat(),
    )
    return stream_course_grades_csv(course)


@teacher_required
@require_http_methods(["GET"])
@ratelimit(key="user", rate="10/m", block=True)
def teacher_course_progress_export_view(request, slug: str):
    """
    Exports per-course progress CSV (rate limited 10/min per user, logged).
    Only counts published lessons.
    """
    course = get_object_or_404(Course, slug=slug)
    logger.info(
        "Course progress CSV export: user_id=%s, course_slug=%s, timestamp=%s",
        request.user.id,
        course.slug,
        timezone.now().isoformat(),
    )
    return stream_course_progress_csv(course)
