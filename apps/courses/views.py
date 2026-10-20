from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.models import SiteSettings
from apps.core.utils import serialize_json_ld
from apps.courses.models import Course, Enrollment


def course_list_view(request):
    """
    Public catalog of published, non-archived courses with search and filtering.
    """
    q = request.GET.get("q", "").strip()
    filter_param = request.GET.get("filter", "all").strip().lower()
    if filter_param not in {"all", "free", "paid"}:
        filter_param = "all"

    queryset = Course.objects.filter(is_published=True, is_archived=False)

    if q:
        queryset = queryset.filter(
            Q(title__icontains=q) | Q(short_description__icontains=q) | Q(description__icontains=q)
        )

    if filter_param == "free":
        queryset = queryset.filter(is_free=True)
    elif filter_param == "paid":
        queryset = queryset.filter(is_free=False)

    # Avoid join multiplication using distinct=True on count
    queryset = queryset.annotate(
        lesson_count=Count("lessons", filter=Q(lessons__is_published=True), distinct=True)
    ).order_by("-is_featured", "-created_at")

    paginator = Paginator(queryset, 9)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "courses": page_obj.object_list,
        "q": q,
        "filter_param": filter_param,
        "total_courses": paginator.count,
    }
    return render(request, "courses/course_list.html", context)


def course_detail_view(request, slug):
    """
    Public overview and syllabus of a single published course.
    """
    course = get_object_or_404(Course, slug=slug, is_published=True, is_archived=False)
    lessons = course.lessons.filter(is_published=True).order_by("order", "id")

    # Sanitize lessons: NEVER expose video_id of non-preview lessons in the HTML
    syllabus_lessons = []
    for lesson in lessons:
        syllabus_lessons.append(
            {
                "id": lesson.id,
                "title": lesson.title,
                "description": lesson.description,
                "order": lesson.order,
                "duration": lesson.duration,
                "is_preview": lesson.is_preview,
                "video_id": lesson.video_id if lesson.is_preview else "",
                "video_provider": lesson.video_provider if lesson.is_preview else "",
            }
        )

    # Enrollment state for current user
    user_enrollment = None
    if request.user.is_authenticated:
        user_enrollment = Enrollment.objects.filter(student=request.user, course=course).first()

    # Generate JSON-LD Schema.org/Course
    site_settings = SiteSettings.get_solo()
    course_schema = {
        "@context": "https://schema.org",
        "@type": "Course",
        "name": course.title,
        "description": course.short_description or course.title,
        "url": f"{settings.SITE_URL}/courses/{course.slug}/",
        "provider": {
            "@type": "Organization",
            "name": site_settings.site_name,
            "sameAs": settings.SITE_URL,
        },
    }
    if course.thumbnail:
        course_schema["image"] = f"{settings.SITE_URL}{course.thumbnail.url}"

    if course.is_free:
        course_schema["isAccessibleForFree"] = True
    else:
        course_schema["isAccessibleForFree"] = False
        course_schema["offers"] = {
            "@type": "Offer",
            "price": str(course.price),
            "priceCurrency": course.currency,
            "availability": "https://schema.org/PreOrder",
        }

    json_ld_raw = serialize_json_ld(course_schema)

    context = {
        "course": course,
        "syllabus_lessons": syllabus_lessons,
        "lesson_count": len(syllabus_lessons),
        "user_enrollment": user_enrollment,
        "json_ld_raw": json_ld_raw,
    }
    return render(request, "courses/course_detail.html", context)


@require_POST
@login_required
def course_enroll_view(request, slug):
    """
    Handles student enrollment requests for free courses.
    Race-safe execution via select_for_update and transaction.atomic().
    """
    course = get_object_or_404(Course, slug=slug, is_published=True, is_archived=False)

    if not course.is_free:
        messages.info(request, _("Enrollment opens soon."))
        return redirect("courses:detail", slug=course.slug)

    with transaction.atomic():
        existing = (
            Enrollment.objects.select_for_update()
            .filter(student=request.user, course=course)
            .first()
        )
        if existing:
            if existing.status == Enrollment.Status.REVOKED:
                messages.error(request, _("Access removed, please contact the teacher."))
            elif existing.status == Enrollment.Status.ACTIVE:
                messages.info(request, _("You are already enrolled in this course."))
            else:
                messages.info(request, _("Your enrollment request is already pending approval."))
            return redirect("courses:detail", slug=course.slug)

        status = Enrollment.Status.PENDING if course.requires_approval else Enrollment.Status.ACTIVE
        try:
            Enrollment.objects.create(
                student=request.user,
                course=course,
                status=status,
                source=Enrollment.Source.FREE,
            )
        except IntegrityError:
            messages.info(request, _("Enrollment already processed."))
            return redirect("courses:detail", slug=course.slug)

    if course.requires_approval:
        messages.success(request, _("Your enrollment request has been submitted for review."))
    else:
        messages.success(request, _("You have successfully enrolled in this course!"))

    return redirect("courses:detail", slug=course.slug)
