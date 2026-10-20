from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.accounts.permissions import teacher_required
from apps.courses.models import Enrollment, Lesson, LessonProgress


@login_required
def student_dashboard(request):
    """
    Student dashboard displaying active enrolled courses with progress tracking,
    pending enrollment requests, and smart resume links.
    Executed in bounded O(1) queries regardless of course count.
    """
    # 1. Active enrollments for published courses (including archived courses where student is enrolled)
    active_enrollments = list(
        Enrollment.objects.filter(
            student=request.user,
            status=Enrollment.Status.ACTIVE,
            course__is_published=True,
        )
        .select_related("course")
        .order_by("-created_at")
    )

    # 2. Pending enrollments for non-archived published courses
    pending_enrollments = list(
        Enrollment.objects.filter(
            student=request.user,
            status=Enrollment.Status.PENDING,
            course__is_published=True,
            course__is_archived=False,
        )
        .select_related("course")
        .order_by("-created_at")
    )

    active_course_ids = [e.course_id for e in active_enrollments]

    # Pre-fetch all published lessons for active courses in 1 query
    all_published_lessons = list(
        Lesson.objects.filter(course_id__in=active_course_ids, is_published=True).order_by(
            "course_id", "order", "id"
        )
    )
    lessons_by_course = {}
    for lesson in all_published_lessons:
        lessons_by_course.setdefault(lesson.course_id, []).append(lesson)

    # Pre-fetch student's LessonProgress records for active courses in 1 query
    user_progress_records = list(
        LessonProgress.objects.filter(
            student=request.user,
            lesson__course_id__in=active_course_ids,
            lesson__is_published=True,
        ).select_related("lesson")
    )
    # Map progress: course_id -> {lesson_id: progress}
    progress_by_course = {}
    for p in user_progress_records:
        progress_by_course.setdefault(p.lesson.course_id, {})[p.lesson_id] = p

    # Build active course card metadata
    active_cards = []
    for enrollment in active_enrollments:
        course = enrollment.course
        course_lessons = lessons_by_course.get(course.id, [])
        course_progress = progress_by_course.get(course.id, {})

        total_lessons = len(course_lessons)
        completed_lessons = sum(
            1
            for les in course_lessons
            if les.id in course_progress and course_progress[les.id].completed_at
        )
        progress_percentage = (
            round((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0
        )

        # Determine continue lesson:
        # 1. Unfinished lesson with latest updated_at
        continue_lesson = None
        unfinished_progress = [
            p
            for p in course_progress.values()
            if p.completed_at is None and p.lesson_id in {les.id for les in course_lessons}
        ]
        if unfinished_progress:
            unfinished_progress.sort(key=lambda p: p.updated_at, reverse=True)
            continue_lesson = unfinished_progress[0].lesson
        else:
            # 2. First lesson in order without completed_at
            completed_ids = {lid for lid, p in course_progress.items() if p.completed_at}
            for les in course_lessons:
                if les.id not in completed_ids:
                    continue_lesson = les
                    break

        # 3. Fallback to first lesson
        if not continue_lesson and course_lessons:
            continue_lesson = course_lessons[0]

        active_cards.append(
            {
                "enrollment": enrollment,
                "course": course,
                "total_lessons": total_lessons,
                "completed_lessons": completed_lessons,
                "progress_percentage": progress_percentage,
                "continue_lesson": continue_lesson,
            }
        )

    context = {
        "active_cards": active_cards,
        "pending_enrollments": pending_enrollments,
        "has_enrollments": bool(active_cards or pending_enrollments),
    }
    return render(request, "dashboard/student_dashboard.html", context)


@teacher_required
def teacher_dashboard(request):
    """
    Placeholder teacher portal for managing content, enrollments, and grading.
    """
    return render(request, "dashboard/teacher_dashboard.html")
