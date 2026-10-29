import logging
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required
from apps.assignments.models import Submission
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.courses.models import (
    Course,
    DownloadRequest,
    Enrollment,
    EnrollmentEvent,
    Lesson,
    LessonProgress,
)

logger = logging.getLogger(__name__)
KATHMANDU_TZ = ZoneInfo("Asia/Kathmandu")


@teacher_required
@require_http_methods(["GET"])
@ratelimit(key="user", rate="60/m", block=True)
def teacher_students_list_view(request):
    """
    Teacher student directory:
    - Lists student accounts (role=student) 25 per page
    - Search by email, first name, last name (rate limited per user)
    - Subquery calculations for active course count and last activity (no join multiplication)
    - Filter by active status and enrolled course
    """
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "all").strip().lower()
    course_slug = request.GET.get("course", "all").strip()

    # Subqueries for last progress and last submission
    last_prog_sub = (
        LessonProgress.objects.filter(student=OuterRef("pk"))
        .order_by("-updated_at")
        .values("updated_at")[:1]
    )
    last_sub_sub = (
        Submission.objects.filter(student=OuterRef("pk"))
        .order_by("-submitted_at")
        .values("submitted_at")[:1]
    )
    active_courses_sub = Subquery(
        Enrollment.objects.filter(student=OuterRef("pk"), status=Enrollment.Status.ACTIVE)
        .values("student")
        .annotate(cnt=Count("id"))
        .values("cnt")[:1],
        output_field=IntegerField(),
    )

    qs = (
        User.objects.filter(role=User.Role.STUDENT)
        .annotate(
            last_prog=Subquery(last_prog_sub),
            last_sub=Subquery(last_sub_sub),
            active_courses_count=Coalesce(active_courses_sub, Value(0)),
        )
        .annotate(
            last_active=Case(
                When(
                    last_prog__isnull=False,
                    last_sub__isnull=False,
                    then=Greatest("last_prog", "last_sub"),
                ),
                When(last_prog__isnull=False, last_sub__isnull=True, then="last_prog"),
                When(last_prog__isnull=True, last_sub__isnull=False, then="last_sub"),
                default=None,
            )
        )
    )

    if search_query:
        qs = qs.filter(
            Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
        )

    if status_filter == "active":
        qs = qs.filter(is_active=True)
    elif status_filter == "inactive":
        qs = qs.filter(is_active=False)

    selected_course = None
    if course_slug and course_slug != "all":
        selected_course = get_object_or_404(Course, slug=course_slug)
        qs = qs.filter(enrollments__course=selected_course).distinct()

    qs = qs.order_by(F("last_active").desc(nulls_last=True), "-date_joined")

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Base counts
    base_students = User.objects.filter(role=User.Role.STUDENT)
    if selected_course:
        base_students = base_students.filter(enrollments__course=selected_course).distinct()

    total_count = base_students.count()
    active_count = base_students.filter(is_active=True).count()
    inactive_count = base_students.filter(is_active=False).count()

    courses = Course.objects.all().order_by("title")

    context = {
        "page_obj": page_obj,
        "students": page_obj,
        "search_query": search_query,
        "status_filter": status_filter,
        "course_slug": course_slug,
        "selected_course": selected_course,
        "courses": courses,
        "total_count": total_count,
        "active_count": active_count,
        "inactive_count": inactive_count,
    }
    return render(request, "dashboard/students/student_list.html", context)


@teacher_required
@require_http_methods(["GET"])
def teacher_student_detail_view(request, student_id: int):
    """
    Teacher view of a student's profile:
    - Enrolled courses with published-lesson completion percentages
    - Assignment submissions and grades
    - Download requests history
    - EnrollmentEvent audit history
    - Account deactivation status & action
    """
    student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)

    # Enrollments with detailed course progress
    enrollments = (
        Enrollment.objects.filter(student=student).select_related("course").order_by("-created_at")
    )

    course_data = []
    for enr in enrollments:
        crs = enr.course
        published_lessons = list(
            Lesson.objects.filter(course=crs, is_published=True).values_list("id", flat=True)
        )
        total_published_lessons = len(published_lessons)
        completed_lessons = 0
        if total_published_lessons > 0:
            completed_lessons = LessonProgress.objects.filter(
                student=student,
                lesson_id__in=published_lessons,
                completed_at__isnull=False,
            ).count()
            progress_pct = round((completed_lessons / total_published_lessons) * 100, 1)
        else:
            progress_pct = 0.0

        # Submissions for this course
        subs = (
            Submission.objects.filter(student=student, assignment__course=crs)
            .select_related("assignment")
            .order_by("-submitted_at")
        )

        course_data.append(
            {
                "enrollment": enr,
                "course": crs,
                "total_lessons": total_published_lessons,
                "completed_lessons": completed_lessons,
                "progress_pct": progress_pct,
                "submissions": subs,
            }
        )

    # Download requests history
    download_requests = (
        DownloadRequest.objects.filter(student=student)
        .select_related(
            "material_item", "material_item__material", "material_item__material__course"
        )
        .order_by("-created_at")[:50]
    )

    # Enrollment events audit log (Requirement 8)
    enrollment_events = (
        EnrollmentEvent.objects.filter(enrollment__student=student)
        .select_related("enrollment__course", "actor")
        .order_by("-created_at")[:50]
    )

    # Deactivation guard checks (Requirement 7)
    can_toggle_active = (
        student != request.user
        and not student.is_staff
        and not student.is_superuser
        and student.role == User.Role.STUDENT
    )

    context = {
        "student": student,
        "course_data": course_data,
        "download_requests": download_requests,
        "enrollment_events": enrollment_events,
        "can_toggle_active": can_toggle_active,
    }
    return render(request, "dashboard/students/student_detail.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_student_toggle_active_view(request, student_id: int):
    """
    Deactivates or reactivates a student account with strict safeguards (Requirement 7):
    - Blocked for self
    - Blocked for other teachers, staff, or superusers
    - Only valid for student accounts
    """
    student = get_object_or_404(User, pk=student_id)

    # Guard 1: Cannot deactivate own account
    if student == request.user:
        messages.error(request, _("You cannot deactivate your own account."))
        return redirect("dashboard:teacher_students")

    # Guard 2: Blocked for other teachers, staff, or superusers
    if student.is_staff or student.is_superuser or student.role != User.Role.STUDENT:
        messages.error(
            request,
            _(
                "Teachers can only deactivate student accounts. Teacher and administrative accounts are protected."
            ),
        )
        return redirect("dashboard:teacher_students")

    new_active = not student.is_active
    student.is_active = new_active
    student.save(update_fields=["is_active"])

    action_label = _("reactivated") if new_active else _("deactivated")
    logger.info(
        "Teacher %s %s student account %s (id=%s)",
        request.user.id,
        "reactivated" if new_active else "deactivated",
        student.email,
        student.id,
    )
    messages.success(
        request,
        _("Student account '%(email)s' has been %(action)s.")
        % {"email": student.email, "action": action_label},
    )

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard:teacher_student_detail", student_id=student.id)
