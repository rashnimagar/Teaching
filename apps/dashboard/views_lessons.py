import logging

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import teacher_required
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.courses.models import Course, CourseMaterial, Lesson, LessonProgress
from apps.dashboard.forms_teacher import TeacherLessonForm

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET"])
def teacher_lessons_list_view(request, slug):
    """
    List all sequential video lessons for a course with accessible
    reordering controls, video provider badges, preview toggles, and assignment counts.
    """
    course = get_object_or_404(Course, slug=slug)
    lessons = list(
        course.lessons.all()
        .annotate(assignments_count=Count("assignments"))
        .order_by("order", "id")
    )

    context = {
        "course": course,
        "lessons": lessons,
        "moved_id": request.GET.get("moved"),
    }
    return render(request, "dashboard/lessons/lesson_list.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_lesson_create_view(request, slug):
    """
    Add a new lesson to a course with automatic order calculation.
    """
    course = get_object_or_404(Course, slug=slug)

    if request.method == "POST":
        form = TeacherLessonForm(request.POST, course=course)
        if form.is_valid():
            with transaction.atomic():
                max_order = Lesson.objects.filter(course=course).aggregate(m=Max("order"))["m"] or 0
                lesson = form.save(commit=False)
                lesson.order = max_order + 1
                lesson.save()

            logger.info(
                "Teacher %s created lesson %s in course %s (ID %s)",
                request.user.id,
                lesson.title,
                course.slug,
                lesson.id,
            )
            messages.success(
                request, _("Lesson '%(title)s' created successfully.") % {"title": lesson.title}
            )
            return redirect("dashboard:teacher_course_lessons", slug=course.slug)
    else:
        form = TeacherLessonForm(course=course)

    context = {
        "form": form,
        "course": course,
        "lesson": None,
        "is_create": True,
        "student_progress_count": 0,
    }
    return render(request, "dashboard/lessons/lesson_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_lesson_edit_view(request, slug, lesson_id):
    """
    Edit an existing lesson. If video ID or provider is changed,
    resets last_position_seconds for students on that lesson (keeping completed_at)
    and informs the teacher how many students were affected.
    """
    course = get_object_or_404(Course, slug=slug)
    lesson = get_object_or_404(Lesson, pk=lesson_id, course=course)

    old_video_id = lesson.video_id
    old_provider = lesson.video_provider

    if request.method == "POST":
        form = TeacherLessonForm(request.POST, instance=lesson, course=course)
        if form.is_valid():
            with transaction.atomic():
                updated_lesson = form.save()

                # Requirement 7: Check if video changed and reset position seconds
                video_changed = (
                    updated_lesson.video_id != old_video_id
                    or updated_lesson.video_provider != old_provider
                )
                affected_count = 0
                if video_changed:
                    affected_count = LessonProgress.objects.filter(
                        lesson=updated_lesson,
                        last_position_seconds__gt=0,
                    ).update(last_position_seconds=0)

                    logger.info(
                        "Teacher %s changed video for lesson %s (ID %s). Reset watch position for %s students.",
                        request.user.id,
                        updated_lesson.title,
                        updated_lesson.id,
                        affected_count,
                    )

            if video_changed and affected_count > 0:
                messages.success(
                    request,
                    _(
                        "Lesson '%(title)s' updated. Reset playback position for %(count)s student(s) due to video replacement."
                    )
                    % {"title": updated_lesson.title, "count": affected_count},
                )
            else:
                messages.success(
                    request,
                    _("Lesson '%(title)s' updated successfully.") % {"title": updated_lesson.title},
                )

            return redirect("dashboard:teacher_course_lessons", slug=course.slug)
    else:
        form = TeacherLessonForm(instance=lesson, course=course)

    context = {
        "form": form,
        "course": course,
        "lesson": lesson,
        "is_create": False,
        "student_progress_count": lesson.progress.count(),
    }
    return render(request, "dashboard/lessons/lesson_form.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_lesson_toggle_publish_view(request, slug, lesson_id):
    """
    Toggle a lesson's published status.
    """
    course = get_object_or_404(Course, slug=slug)
    lesson = get_object_or_404(Lesson, pk=lesson_id, course=course)

    lesson.is_published = not lesson.is_published
    lesson.save(update_fields=["is_published", "updated_at"])

    status_str = "published" if lesson.is_published else "unpublished"
    logger.info(
        "Teacher %s %s lesson %s (ID %s)", request.user.id, status_str, lesson.title, lesson.id
    )

    messages.success(
        request,
        _("Lesson '%(title)s' is now %(status)s.")
        % {
            "title": lesson.title,
            "status": _("published") if lesson.is_published else _("hidden as draft"),
        },
    )
    return redirect("dashboard:teacher_course_lessons", slug=course.slug)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_lesson_reorder_view(request, slug, lesson_id):
    """
    Reorder a lesson up or down within its course in transaction.atomic()
    with the course's lessons locked. Gaps are handled and sequence normalized.
    """
    course = get_object_or_404(Course, slug=slug)
    direction = request.POST.get("direction", "up")

    with transaction.atomic():
        # Lock lessons belonging to this course
        lessons = list(
            Lesson.objects.select_for_update().filter(course=course).order_by("order", "id")
        )

        target_idx = None
        for idx, les in enumerate(lessons):
            if les.id == lesson_id:
                target_idx = idx
                break

        if target_idx is None:
            raise Http404(_("Lesson does not belong to this course."))

        if direction == "up" and target_idx > 0:
            swap_idx = target_idx - 1
            lessons[target_idx], lessons[swap_idx] = lessons[swap_idx], lessons[target_idx]
        elif direction == "down" and target_idx < len(lessons) - 1:
            swap_idx = target_idx + 1
            lessons[target_idx], lessons[swap_idx] = lessons[swap_idx], lessons[target_idx]

        # Re-normalize order values to 1, 2, 3...
        for new_order, les in enumerate(lessons, start=1):
            if les.order != new_order:
                les.order = new_order
                les.save(update_fields=["order", "updated_at"])

        logger.info(
            "Teacher %s reordered lesson ID %s %s in course %s",
            request.user.id,
            lesson_id,
            direction,
            course.slug,
        )

    url = reverse("dashboard:teacher_course_lessons", kwargs={"slug": course.slug})
    return redirect(f"{url}?moved={lesson_id}")


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_lesson_delete_view(request, slug, lesson_id):
    """
    Safely delete a lesson only if it has no dependent student data
    (lesson progress records, linked assignments, or linked materials).
    Otherwise, blocks deletion and offers unpublishing.
    """
    course = get_object_or_404(Course, slug=slug)
    lesson = get_object_or_404(Lesson, pk=lesson_id, course=course)

    # Check dependents
    has_progress = lesson.progress.exists()
    has_assignments = lesson.assignments.exists()
    has_materials = CourseMaterial.objects.filter(lesson=lesson).exists()

    if has_progress or has_assignments or has_materials:
        reasons = []
        if has_progress:
            reasons.append(str(_("student watch progress records exist")))
        if has_assignments:
            reasons.append(str(_("linked assignments exist")))
        if has_materials:
            reasons.append(str(_("linked course materials exist")))

        logger.warning(
            "Teacher %s attempted to delete lesson %s (ID %s) but was blocked: %s",
            request.user.id,
            lesson.title,
            lesson.id,
            ", ".join(reasons),
        )

        messages.error(
            request,
            _(
                "Cannot delete lesson '%(title)s' because %(reasons)s. You can unpublish it instead to hide it from students."
            )
            % {"title": lesson.title, "reasons": ", ".join(reasons)},
        )
        return redirect("dashboard:teacher_course_lessons", slug=course.slug)

    lesson_title = lesson.title
    with transaction.atomic():
        lesson.delete()
        # Normalize remaining lessons
        remaining = Lesson.objects.filter(course=course).order_by("order", "id")
        for new_order, les in enumerate(remaining, start=1):
            if les.order != new_order:
                les.order = new_order
                les.save(update_fields=["order", "updated_at"])

    logger.info(
        "Teacher %s deleted lesson '%s' (ID %s) from course %s",
        request.user.id,
        lesson_title,
        lesson_id,
        course.slug,
    )
    messages.success(
        request, _("Lesson '%(title)s' deleted successfully.") % {"title": lesson_title}
    )
    return redirect("dashboard:teacher_course_lessons", slug=course.slug)
