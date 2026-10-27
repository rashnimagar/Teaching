from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, DownloadRequest, Enrollment, Lesson, LessonProgress


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
    active_course_ids_set = set(active_course_ids)

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
        ).select_related("lesson", "lesson__course")
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

        # Determine continue lesson for the card:
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

    # Determine global continue learning hero for the latest touched unfinished lesson
    # Hidden for new students who have no progress records or whose started lessons are all complete
    continue_learning_hero = None
    unfinished_global = [
        p
        for p in user_progress_records
        if p.completed_at is None and p.lesson.course_id in active_course_ids_set
    ]
    if unfinished_global:
        latest_p = max(unfinished_global, key=lambda p: p.updated_at)
        h_course = latest_p.lesson.course
        h_lessons = lessons_by_course.get(h_course.id, [])
        h_progress = progress_by_course.get(h_course.id, {})
        h_total = len(h_lessons)
        h_completed = sum(
            1 for les in h_lessons if les.id in h_progress and h_progress[les.id].completed_at
        )
        h_pct = round((h_completed / h_total) * 100) if h_total > 0 else 0
        continue_learning_hero = {
            "lesson": latest_p.lesson,
            "course": h_course,
            "progress_percentage": h_pct,
            "completed_lessons": h_completed,
            "total_lessons": h_total,
            "last_position_seconds": latest_p.last_position_seconds,
            "updated_at": latest_p.updated_at,
        }

    context = {
        "active_cards": active_cards,
        "pending_enrollments": pending_enrollments,
        "has_enrollments": bool(active_cards or pending_enrollments),
        "continue_learning_hero": continue_learning_hero,
    }
    return render(request, "dashboard/student_dashboard.html", context)


@teacher_required
def teacher_dashboard(request):
    """
    Teacher administration portal shell displaying real live metrics,
    quick navigation links, and recent student activity feeds.
    """
    now = timezone.now()

    # Requirement 9: Active students = students with at least one active enrollment
    active_students_count = (
        User.objects.filter(
            role=User.Role.STUDENT,
            enrollments__status=Enrollment.Status.ACTIVE,
        )
        .distinct()
        .count()
    )

    published_courses_count = Course.objects.filter(is_published=True, is_archived=False).count()
    pending_enrollments_count = Enrollment.objects.filter(status=Enrollment.Status.PENDING).count()
    pending_permissions_count = DownloadRequest.objects.filter(
        status=DownloadRequest.Status.PENDING
    ).count()

    # Requirement 9: Ungraded submissions = ungraded submissions of published assignments in non-archived courses
    ungraded_submissions_count = Submission.objects.filter(
        grade__isnull=True,
        assignment__is_published=True,
        assignment__course__is_archived=False,
    ).count()

    # Deadlines in next 7 days
    upcoming_deadlines_count = Assignment.objects.filter(
        is_published=True,
        course__is_archived=False,
        due_at__gte=now,
        due_at__lte=now + timedelta(days=7),
    ).count()

    # Recent activity lists (bounded O(1) queries)
    recent_submissions = list(
        Submission.objects.filter(
            assignment__is_published=True,
            assignment__course__is_archived=False,
        )
        .select_related("student", "assignment", "assignment__course")
        .order_by("-submitted_at")[:5]
    )

    recent_enrollments = list(
        Enrollment.objects.select_related("student", "course").order_by("-created_at")[:5]
    )

    recent_requests = list(
        DownloadRequest.objects.select_related(
            "student", "material_item", "material_item__material__course"
        ).order_by("-requested_at")[:5]
    )

    context = {
        "active_students_count": active_students_count,
        "published_courses_count": published_courses_count,
        "pending_enrollments_count": pending_enrollments_count,
        "ungraded_submissions_count": ungraded_submissions_count,
        "pending_permissions_count": pending_permissions_count,
        "upcoming_deadlines_count": upcoming_deadlines_count,
        "recent_submissions": recent_submissions,
        "recent_enrollments": recent_enrollments,
        "recent_requests": recent_requests,
        "teacher_courses_url": reverse("dashboard:teacher_courses"),
        "teacher_permissions_url": reverse("dashboard:teacher_permissions"),
        "admin_courses_url": reverse("admin:courses_course_changelist"),
        "admin_pending_enrollments_url": (
            f"{reverse('admin:courses_enrollment_changelist')}?status__exact=pending"
        ),
        "admin_site_settings_url": reverse("admin:core_sitesettings_changelist"),
        "admin_submissions_url": (
            f"{reverse('admin:assignments_submission_changelist')}?grade__isnull=True"
        ),
        "admin_index_url": reverse("admin:index"),
    }
    return render(request, "dashboard/teacher_dashboard.html", context)
