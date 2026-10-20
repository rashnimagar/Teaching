from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.models import SiteSettings
from apps.core.utils import serialize_json_ld
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress
from apps.courses.permissions import check_lesson_access
from apps.courses.services.video import build_safe_video_embed_url


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
    Active enrolled students and staff retain access to archived courses.
    """
    course = get_object_or_404(Course, slug=slug, is_published=True)
    if course.is_archived:
        is_active_student = (
            request.user.is_authenticated
            and Enrollment.objects.filter(
                student=request.user, course=course, status=Enrollment.Status.ACTIVE
            ).exists()
        )
        if not (request.user.is_authenticated and (request.user.is_staff or is_active_student)):
            raise Http404(_("Course not found."))

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


def course_learn_redirect_view(request, course_slug):
    """
    Redirects student to their current learning milestone in the course:
    1. The last unfinished lesson with recorded progress.
    2. The first published lesson in syllabus order without completed progress.
    3. The first published lesson in syllabus order.
    """
    course = get_object_or_404(Course, slug=course_slug)
    is_allowed, redirect_resp = check_lesson_access(request, course)
    if not is_allowed:
        return redirect_resp

    published_lessons = list(course.lessons.filter(is_published=True).order_by("order", "id"))
    if not published_lessons:
        raise Http404(_("No published lessons are available in this course."))

    target_lesson = None

    if request.user.is_authenticated:
        # Check for recently touched unfinished lesson
        in_progress = (
            LessonProgress.objects.filter(
                student=request.user,
                lesson__course=course,
                lesson__is_published=True,
                completed_at__isnull=True,
            )
            .order_by("-updated_at")
            .select_related("lesson")
            .first()
        )
        if in_progress:
            target_lesson = in_progress.lesson
        else:
            completed_lesson_ids = set(
                LessonProgress.objects.filter(
                    student=request.user,
                    lesson__course=course,
                    lesson__is_published=True,
                    completed_at__isnull=False,
                ).values_list("lesson_id", flat=True)
            )
            for lesson in published_lessons:
                if lesson.id not in completed_lesson_ids:
                    target_lesson = lesson
                    break

    if not target_lesson:
        target_lesson = published_lessons[0]

    return redirect("learn:lesson", course_slug=course.slug, lesson_id=target_lesson.id)


def lesson_learn_view(request, course_slug, lesson_id):
    """
    Main lesson viewing interface with embedded video player, lesson syllabus,
    previous/next lesson navigation, and course assignments.
    Sets Cache-Control: private, no-store.
    """
    course = get_object_or_404(Course, slug=course_slug)
    lesson = get_object_or_404(Lesson, pk=lesson_id, course=course)

    is_allowed, redirect_resp = check_lesson_access(request, course, lesson)
    if not is_allowed:
        return redirect_resp

    # Lessons available in the syllabus sidebar
    if request.user.is_authenticated and request.user.is_staff:
        all_syllabus_lessons = list(course.lessons.all().order_by("order", "id"))
    else:
        all_syllabus_lessons = list(
            course.lessons.filter(is_published=True).order_by("order", "id")
        )

    # Determine previous and next published lessons
    published_lessons = [les for les in all_syllabus_lessons if les.is_published]
    prev_lesson = None
    next_lesson = None
    for idx, les in enumerate(published_lessons):
        if les.id == lesson.id:
            if idx > 0:
                prev_lesson = published_lessons[idx - 1]
            if idx < len(published_lessons) - 1:
                next_lesson = published_lessons[idx + 1]
            break

    # Load progress map for current student
    progress_map = {}
    if request.user.is_authenticated:
        progress_records = LessonProgress.objects.filter(
            student=request.user, lesson__course=course
        ).select_related("lesson")
        progress_map = {p.lesson_id: p for p in progress_records}

    # Published lesson stats
    total_published = len(published_lessons)
    completed_count = sum(
        1
        for les in published_lessons
        if les.id in progress_map and progress_map[les.id].completed_at
    )
    progress_percentage = (
        round((completed_count / total_published) * 100) if total_published > 0 else 0
    )

    current_progress = progress_map.get(lesson.id)
    last_position_seconds = current_progress.last_position_seconds if current_progress else 0
    is_current_completed = bool(current_progress and current_progress.completed_at)

    # Safe embed URL (only built for the active requested lesson)
    embed_url = build_safe_video_embed_url(
        lesson.video_provider, lesson.video_id, lesson.video_hash
    )

    # User enrollment status for syllabus lock indicators
    is_active_enrolled = request.user.is_authenticated and (
        request.user.is_staff
        or Enrollment.objects.filter(
            student=request.user, course=course, status=Enrollment.Status.ACTIVE
        ).exists()
    )

    # Format syllabus lessons: NEVER leak video_id or embed URL of other lessons
    sidebar_items = []
    for les in all_syllabus_lessons:
        les_progress = progress_map.get(les.id)
        is_completed = bool(les_progress and les_progress.completed_at)
        is_accessible = is_active_enrolled or les.is_preview
        sidebar_items.append(
            {
                "id": les.id,
                "title": les.title,
                "order": les.order,
                "duration": les.duration,
                "is_preview": les.is_preview,
                "is_published": les.is_published,
                "is_current": les.id == lesson.id,
                "is_completed": is_completed,
                "is_accessible": is_accessible,
            }
        )

    # Course assignments
    assignments = course.assignments.select_related("lesson").order_by("due_at")

    context = {
        "course": course,
        "lesson": lesson,
        "prev_lesson": prev_lesson,
        "next_lesson": next_lesson,
        "embed_url": embed_url,
        "last_position_seconds": last_position_seconds,
        "is_current_completed": is_current_completed,
        "sidebar_items": sidebar_items,
        "assignments": assignments,
        "total_published": total_published,
        "completed_count": completed_count,
        "progress_percentage": progress_percentage,
        "is_active_enrolled": is_active_enrolled,
    }

    response = render(request, "courses/lesson_learn.html", context)
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
@login_required
@ratelimit(key="user", rate="60/m", block=True)
def lesson_toggle_complete_view(request, course_slug, lesson_id):
    """
    Toggles completion state for a lesson.
    Keyed by authenticated user. Race-safe via update_or_create.
    """
    course = get_object_or_404(Course, slug=course_slug)
    lesson = get_object_or_404(Lesson, pk=lesson_id, course=course)

    is_allowed, err_resp = check_lesson_access(request, course, lesson, is_api=True)
    if not is_allowed:
        return err_resp

    progress = LessonProgress.objects.filter(student=request.user, lesson=lesson).first()
    if progress and progress.completed_at:
        new_completed_at = None
        is_completed = False
    else:
        new_completed_at = timezone.now()
        is_completed = True

    progress, _ = LessonProgress.objects.update_or_create(
        student=request.user,
        lesson=lesson,
        defaults={"completed_at": new_completed_at},
    )

    total_published = course.lessons.filter(is_published=True).count()
    completed_count = LessonProgress.objects.filter(
        student=request.user,
        lesson__course=course,
        lesson__is_published=True,
        completed_at__isnull=False,
    ).count()
    progress_percentage = (
        round((completed_count / total_published) * 100) if total_published > 0 else 0
    )

    return JsonResponse(
        {
            "completed": is_completed,
            "progress_percentage": progress_percentage,
            "completed_count": completed_count,
            "total_count": total_published,
        }
    )


@require_POST
@login_required
@ratelimit(key="user", rate="120/m", block=True)
def lesson_playback_position_view(request, course_slug, lesson_id):
    """
    Records playback position for resume functionality.
    Keyed by authenticated user. Race-safe via update_or_create.
    """
    course = get_object_or_404(Course, slug=course_slug)
    lesson = get_object_or_404(Lesson, pk=lesson_id, course=course)

    is_allowed, err_resp = check_lesson_access(request, course, lesson, is_api=True)
    if not is_allowed:
        return err_resp

    raw_pos = request.POST.get("position")
    try:
        position = int(raw_pos)
        if position < 0 or position > 86400:
            return JsonResponse({"error": _("Position out of valid range.")}, status=400)
    except (TypeError, ValueError):
        return JsonResponse({"error": _("Invalid position value.")}, status=400)

    LessonProgress.objects.update_or_create(
        student=request.user,
        lesson=lesson,
        defaults={"last_position_seconds": position},
    )

    return JsonResponse({"status": "ok", "position": position})
