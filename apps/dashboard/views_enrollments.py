import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.accounts.models import User
from apps.accounts.permissions import teacher_required
from apps.courses.models import Course, Enrollment, EnrollmentEvent
from apps.courses.services.enrollments import transition_enrollment_status

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET"])
def teacher_enrollments_list_view(request):
    """
    Teacher enrollment queue with filtering by status (pending, active, revoked),
    course selection, student email/name search, and pagination.
    """
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "all").strip().lower()
    course_slug = request.GET.get("course", "all").strip()

    qs = Enrollment.objects.select_related("student", "course").order_by("-created_at")

    if search_query:
        qs = qs.filter(
            Q(student__email__icontains=search_query)
            | Q(student__first_name__icontains=search_query)
            | Q(student__last_name__icontains=search_query)
        )

    # Status filter: strictly pending, active, revoked (Requirement 4: no "expired")
    if status_filter in ("pending", "active", "revoked"):
        qs = qs.filter(status=status_filter)

    selected_course = None
    if course_slug and course_slug != "all":
        selected_course = get_object_or_404(Course, slug=course_slug)
        qs = qs.filter(course=selected_course)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Summary metric counts
    base_qs = Enrollment.objects.all()
    if selected_course:
        base_qs = base_qs.filter(course=selected_course)

    pending_count = base_qs.filter(status=Enrollment.Status.PENDING).count()
    active_count = base_qs.filter(status=Enrollment.Status.ACTIVE).count()
    revoked_count = base_qs.filter(status=Enrollment.Status.REVOKED).count()
    total_count = base_qs.count()

    courses = Course.objects.all().order_by("title")

    context = {
        "page_obj": page_obj,
        "enrollments": page_obj,
        "search_query": search_query,
        "status_filter": status_filter,
        "course_slug": course_slug,
        "selected_course": selected_course,
        "courses": courses,
        "pending_count": pending_count,
        "active_count": active_count,
        "revoked_count": revoked_count,
        "total_count": total_count,
    }
    return render(request, "dashboard/enrollments/enrollment_list.html", context)


@teacher_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="60/m", block=True)
def teacher_enrollment_action_view(request, enrollment_id: int):
    """
    POST-only single enrollment state transition:
    actions: approve (pending->active, revoked->active), revoke (active->revoked, pending->revoked).
    """
    action = request.POST.get("action", "").strip().lower()
    note = request.POST.get("note", "").strip()

    target_status = None
    if action == "approve":
        target_status = Enrollment.Status.ACTIVE
    elif action == "revoke":
        target_status = Enrollment.Status.REVOKED
    else:
        messages.error(request, _("Unsupported enrollment action."))
        return redirect("dashboard:teacher_enrollments")

    try:
        enrollment, success, message = transition_enrollment_status(
            enrollment_id=enrollment_id,
            new_status=target_status,
            actor=request.user,
            note=note,
        )
        if success:
            messages.success(request, message)
        else:
            messages.info(request, message)
    except ValueError as err:
        messages.error(request, str(err))

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard:teacher_enrollments")


@teacher_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="30/m", block=True)
def teacher_enrollments_bulk_action_view(request):
    """
    Bulk enrollment approval or revocation on current page with count summary.
    Skips rows already in target status or with invalid transitions.
    """
    action = request.POST.get("action", "").strip().lower()
    enrollment_ids = request.POST.getlist("enrollment_ids")

    if not enrollment_ids:
        messages.error(request, _("No enrollments selected for bulk action."))
        return redirect("dashboard:teacher_enrollments")

    target_status = None
    if action == "approve":
        target_status = Enrollment.Status.ACTIVE
    elif action == "revoke":
        target_status = Enrollment.Status.REVOKED
    else:
        messages.error(request, _("Unsupported bulk action."))
        return redirect("dashboard:teacher_enrollments")

    success_count = 0
    skipped_count = 0

    for raw_id in enrollment_ids:
        try:
            eid = int(raw_id)
        except ValueError:
            continue

        try:
            _, success, _ = transition_enrollment_status(
                enrollment_id=eid,
                new_status=target_status,
                actor=request.user,
                note=_("Bulk %(action)s action") % {"action": action},
            )
            if success:
                success_count += 1
            else:
                skipped_count += 1
        except ValueError:
            skipped_count += 1

    action_label = _("approved") if target_status == Enrollment.Status.ACTIVE else _("revoked")
    if success_count > 0 and skipped_count > 0:
        messages.success(
            request,
            _(
                "Successfully %(action)s %(success)s enrollment(s). %(skipped)s skipped (already in status or invalid)."
            )
            % {"action": action_label, "success": success_count, "skipped": skipped_count},
        )
    elif success_count > 0:
        messages.success(
            request,
            _("Successfully %(action)s %(success)s enrollment(s).")
            % {"action": action_label, "success": success_count},
        )
    else:
        messages.info(
            request,
            _(
                "No enrollments updated. All %(skipped)s selected enrollment(s) were already in the target status."
            )
            % {"skipped": skipped_count},
        )

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard:teacher_enrollments")


@teacher_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="30/m", block=True)
def teacher_enrollment_manual_view(request):
    """
    Manually enroll an existing student account into a course.
    Requirement 5: Requires an existing student account (role student);
    no account -> clear error. Uses get_or_create against unique (student, course).
    """
    student_email = request.POST.get("email", "").strip().lower()
    course_id = request.POST.get("course_id")

    if not student_email or not course_id:
        messages.error(request, _("Both student email and course selection are required."))
        return redirect("dashboard:teacher_enrollments")

    course = get_object_or_404(Course, pk=course_id)

    # Lookup existing student user
    student = User.objects.filter(email=student_email, role=User.Role.STUDENT).first()
    if not student:
        messages.error(
            request,
            _(
                "No student account found with email '%(email)s'. A student must create an account first."
            )
            % {"email": student_email},
        )
        return redirect("dashboard:teacher_enrollments")

    with transaction.atomic():
        enrollment, created = Enrollment.objects.get_or_create(
            student=student,
            course=course,
            defaults={
                "status": Enrollment.Status.ACTIVE,
                "source": Enrollment.Source.MANUAL,
            },
        )

        if created:
            EnrollmentEvent.objects.create(
                enrollment=enrollment,
                actor=request.user,
                from_status="none",
                to_status=Enrollment.Status.ACTIVE,
                note=_("Manual enrollment added by teacher"),
            )
            logger.info(
                "Teacher %s manually enrolled student %s in course %s",
                request.user.id,
                student.id,
                course.slug,
            )
            messages.success(
                request,
                _("Student '%(email)s' has been enrolled into '%(course)s'.")
                % {"email": student.email, "course": course.title},
            )
        else:
            # If existed, reactivate if revoked or pending
            if enrollment.status != Enrollment.Status.ACTIVE:
                transition_enrollment_status(
                    enrollment_id=enrollment.id,
                    new_status=Enrollment.Status.ACTIVE,
                    actor=request.user,
                    note=_("Manual reactivation by teacher"),
                )
                messages.success(
                    request,
                    _(
                        "Student '%(email)s' enrollment in '%(course)s' has been reactivated to Active."
                    )
                    % {"email": student.email, "course": course.title},
                )
            else:
                messages.info(
                    request,
                    _("Student '%(email)s' is already actively enrolled in '%(course)s'.")
                    % {"email": student.email, "course": course.title},
                )

    return redirect("dashboard:teacher_enrollments")
