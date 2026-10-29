import logging
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment, Submission
from apps.assignments.services.grading import grade_submission, unlock_submission
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.courses.models import Course, Enrollment

logger = logging.getLogger(__name__)
KATHMANDU_TZ = ZoneInfo("Asia/Kathmandu")


@teacher_required
@require_http_methods(["GET"])
def teacher_submissions_list_view(request):
    """
    Global submissions queue with filters for course, assignment,
    grading status (all, ungraded, graded), timeliness (all, on_time, late),
    and search by student email/name.
    """
    search_query = request.GET.get("q", "").strip()
    course_slug = request.GET.get("course", "all").strip()
    status_filter = request.GET.get("status", "all").strip().lower()
    timeliness_filter = request.GET.get("timeliness", "all").strip().lower()

    qs = (
        Submission.objects.select_related("assignment", "assignment__course", "student")
        .filter(assignment__course__is_archived=False)
        .order_by("-submitted_at")
    )

    if search_query:
        qs = qs.filter(
            Q(student__email__icontains=search_query)
            | Q(student__first_name__icontains=search_query)
            | Q(student__last_name__icontains=search_query)
        )

    selected_course = None
    if course_slug and course_slug != "all":
        selected_course = get_object_or_404(Course, slug=course_slug)
        qs = qs.filter(assignment__course=selected_course)

    if status_filter == "ungraded":
        qs = qs.filter(grade__isnull=True)
    elif status_filter == "graded":
        qs = qs.filter(grade__isnull=False)

    if timeliness_filter == "late":
        qs = qs.filter(is_late=True)
    elif timeliness_filter == "on_time":
        qs = qs.filter(is_late=False)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Base counts
    base_qs = Submission.objects.filter(assignment__course__is_archived=False)
    if selected_course:
        base_qs = base_qs.filter(assignment__course=selected_course)

    ungraded_count = base_qs.filter(grade__isnull=True, assignment__is_published=True).count()
    graded_count = base_qs.filter(grade__isnull=False).count()
    late_count = base_qs.filter(is_late=True).count()
    total_count = base_qs.count()

    courses = Course.objects.filter(is_archived=False).order_by("title")

    context = {
        "page_obj": page_obj,
        "submissions": page_obj,
        "search_query": search_query,
        "course_slug": course_slug,
        "status_filter": status_filter,
        "timeliness_filter": timeliness_filter,
        "selected_course": selected_course,
        "courses": courses,
        "ungraded_count": ungraded_count,
        "graded_count": graded_count,
        "late_count": late_count,
        "total_count": total_count,
    }
    return render(request, "dashboard/submissions/submission_list.html", context)


@teacher_required
@require_http_methods(["GET"])
def teacher_course_assignment_submissions_view(request, slug: str, assignment_id: int):
    """
    Submissions queue scoped to a specific assignment within a course.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)

    status_filter = request.GET.get("status", "all").strip().lower()
    search_query = request.GET.get("q", "").strip()
    timeliness_filter = request.GET.get("timeliness", "all").strip().lower()

    qs = (
        Submission.objects.select_related("student", "assignment", "assignment__course")
        .filter(assignment=assignment)
        .order_by("-submitted_at")
    )

    if search_query:
        qs = qs.filter(
            Q(student__email__icontains=search_query)
            | Q(student__first_name__icontains=search_query)
            | Q(student__last_name__icontains=search_query)
        )

    if status_filter == "ungraded":
        qs = qs.filter(grade__isnull=True)
    elif status_filter == "graded":
        qs = qs.filter(grade__isnull=False)

    if timeliness_filter == "late":
        qs = qs.filter(is_late=True)
    elif timeliness_filter == "on_time":
        qs = qs.filter(is_late=False)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    ungraded_count = assignment.submissions.filter(grade__isnull=True).count()
    graded_count = assignment.submissions.filter(grade__isnull=False).count()
    total_count = assignment.submissions.count()
    late_count = assignment.submissions.filter(is_late=True).count()

    # Active students without submission
    now = timezone.now()
    submitted_students = assignment.submissions.values_list("student_id", flat=True)
    missed_count = (
        Enrollment.objects.filter(course=course, status=Enrollment.Status.ACTIVE)
        .exclude(student_id__in=submitted_students)
        .count()
    )

    context = {
        "course": course,
        "course_slug": course.slug,
        "assignment": assignment,
        "page_obj": page_obj,
        "submissions": page_obj,
        "status_filter": status_filter,
        "timeliness_filter": timeliness_filter,
        "search_query": search_query,
        "ungraded_count": ungraded_count,
        "graded_count": graded_count,
        "total_count": total_count,
        "late_count": late_count,
        "missed_count": missed_count,
        "is_past_deadline": now > assignment.due_at,
    }
    return render(request, "dashboard/submissions/submission_list.html", context)


@teacher_required
@require_http_methods(["GET"])
def teacher_missed_deadlines_view(request, slug: str, assignment_id: int):
    """
    Shows students with ACTIVE enrollment in the course who have NOT submitted
    by due_at. Separately marks if the assignment is still open for late submissions.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)

    now = timezone.now()
    is_past_deadline = now > assignment.due_at
    still_open_late = is_past_deadline and assignment.allow_late

    # Active students who have not submitted
    submitted_students = assignment.submissions.values_list("student_id", flat=True)
    active_enrollments = (
        Enrollment.objects.filter(course=course, status=Enrollment.Status.ACTIVE)
        .exclude(student_id__in=submitted_students)
        .select_related("student")
        .order_by("student__first_name", "student__last_name", "student__email")
    )

    paginator = Paginator(active_enrollments, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "course": course,
        "assignment": assignment,
        "page_obj": page_obj,
        "missed_enrollments": page_obj,
        "is_past_deadline": is_past_deadline,
        "still_open_late": still_open_late,
        "total_missed_count": active_enrollments.count(),
    }
    return render(request, "dashboard/submissions/missed_deadlines.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="60/m", block=True)
def teacher_submission_grade_view(request, submission_id: int):
    """
    In-dashboard grading interface:
    - View submitted text and private file download (via existing assignments:download)
    - Submitted time and late flag in Asia/Kathmandu
    - Grade input (0 to max_score), feedback
    - Save & Next button to immediately advance to next ungraded submission
    - Unlock action with confirmation modal and audit trail
    """
    submission = get_object_or_404(
        Submission.objects.select_related(
            "assignment", "assignment__course", "student", "graded_by"
        ),
        pk=submission_id,
    )
    assignment = submission.assignment
    course = assignment.course

    # Next ungraded submission in the same assignment or course
    next_ungraded = (
        Submission.objects.filter(assignment=assignment, grade__isnull=True)
        .exclude(pk=submission.id)
        .order_by("submitted_at")
        .first()
    )
    if not next_ungraded:
        next_ungraded = (
            Submission.objects.filter(assignment__course=course, grade__isnull=True)
            .exclude(pk=submission.id)
            .order_by("submitted_at")
            .first()
        )

    if request.method == "POST":
        raw_grade = request.POST.get("grade", "").strip()
        feedback = request.POST.get("feedback", "").strip()

        if not raw_grade:
            messages.error(request, _("Please provide a numeric grade."))
            return redirect("dashboard:teacher_submission_grade", submission_id=submission.id)

        try:
            grade_val = Decimal(raw_grade)
        except (InvalidOperation, TypeError):
            messages.error(request, _("Grade must be a valid number."))
            return redirect("dashboard:teacher_submission_grade", submission_id=submission.id)

        try:
            sub, success, msg = grade_submission(
                submission_id=submission.id,
                grade=grade_val,
                feedback=feedback,
                teacher_user=request.user,
            )
            if success:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        except Exception as err:  # noqa: BLE001
            messages.error(request, str(err))
            return redirect("dashboard:teacher_submission_grade", submission_id=submission.id)

        # Handle Save & Next Ungraded (Requirement 6)
        if "save_and_next" in request.POST:
            if next_ungraded:
                return redirect(
                    "dashboard:teacher_submission_grade", submission_id=next_ungraded.id
                )
            messages.info(request, _("All ungraded submissions in this section have been graded!"))
            return redirect(
                "dashboard:teacher_course_assignment_submissions",
                slug=course.slug,
                assignment_id=assignment.id,
            )

        return redirect("dashboard:teacher_submission_grade", submission_id=submission.id)

    # Convert submitted_at to Asia/Kathmandu
    submitted_at_npt = submission.submitted_at.astimezone(KATHMANDU_TZ)
    graded_at_npt = submission.graded_at.astimezone(KATHMANDU_TZ) if submission.graded_at else None

    # Audit history
    events = submission.events.select_related("actor").order_by("-created_at")

    download_url = (
        reverse(
            "assignments:download", kwargs={"slug": course.slug, "submission_id": submission.id}
        )
        if submission.file
        else None
    )

    context = {
        "submission": submission,
        "assignment": assignment,
        "course": course,
        "submitted_at_npt": submitted_at_npt,
        "graded_at_npt": graded_at_npt,
        "download_url": download_url,
        "events": events,
        "next_ungraded": next_ungraded,
    }
    return render(request, "dashboard/submissions/submission_grade.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_submission_unlock_view(request, submission_id: int):
    """
    Unlock a submission with a confirmation note and audit event,
    allowing the student to edit and resubmit their work.
    """
    note = request.POST.get("note", "").strip()
    sub, success, msg = unlock_submission(
        submission_id=submission_id,
        teacher_user=request.user,
        note=note,
    )
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    return redirect("dashboard:teacher_submission_grade", submission_id=submission_id)
