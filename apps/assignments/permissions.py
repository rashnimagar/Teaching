from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, resolve_url
from django.utils.translation import gettext_lazy as _

from apps.accounts.permissions import is_teacher_user
from apps.courses.models import Course, Enrollment


def check_assignment_access(request, course: Course, is_api: bool = False):
    """
    Enforces server-side access control for assignment pages and submissions,
    mirroring the course learning and lesson access rules.

    Rules:
    - Unpublished courses return 404 for non-staff.
    - Archived courses return 404 for non-staff UNLESS the student has an ACTIVE enrollment.
    - Teachers and staff have unrestricted access to all courses and assignments.
    - Anonymous users are redirected to login (or 403 in API / download mode).
    - Active enrollment grants full access to course assignments.
    - Pending or revoked enrollments, or non-enrolled users, are blocked:
        - In page views: redirected to course detail with a friendly message.
        - In API endpoints / downloads: returned 403 Forbidden.

    Returns:
        tuple[bool, HttpResponse | None]: (is_allowed, response_if_blocked)
    """
    # 1. Unpublished course check
    if not course.is_published:
        if not is_teacher_user(request.user):
            raise Http404(_("Course not found."))

    # 2. Archived course check: only active enrollments or staff retain access
    if course.is_archived:
        if request.user.is_authenticated:
            is_active_student = Enrollment.objects.filter(
                student=request.user, course=course, status=Enrollment.Status.ACTIVE
            ).exists()
            if not (is_teacher_user(request.user) or is_active_student):
                raise Http404(_("Course not found."))
        else:
            raise Http404(_("Course not found."))

    # 3. Teacher / Staff bypass
    if is_teacher_user(request.user):
        return True, None

    # 4. Anonymous user
    if not request.user.is_authenticated:
        if is_api:
            return False, HttpResponseForbidden(_("Authentication required."))
        login_url = f"{resolve_url(settings.LOGIN_URL)}?next={request.path}"
        return False, redirect(login_url)

    # 5. Student enrollment verification
    enrollment = Enrollment.objects.filter(student=request.user, course=course).first()

    if not enrollment:
        if is_api:
            return False, HttpResponseForbidden(_("Enrollment required to access assignments."))
        messages.info(request, _("Please enroll in this course to access assignments."))
        return False, redirect("courses:detail", slug=course.slug)

    if enrollment.status == Enrollment.Status.PENDING:
        if is_api:
            return False, HttpResponseForbidden(_("Your enrollment is pending approval."))
        messages.info(request, _("Your enrollment request is pending approval."))
        return False, redirect("courses:detail", slug=course.slug)

    if enrollment.status == Enrollment.Status.REVOKED:
        if is_api:
            return False, HttpResponseForbidden(_("Access to this course has been removed."))
        messages.error(
            request, _("Access to this course has been removed, please contact the teacher.")
        )
        return False, redirect("courses:detail", slug=course.slug)

    if enrollment.status == Enrollment.Status.ACTIVE:
        return True, None

    if is_api:
        return False, HttpResponseForbidden(_("Access denied."))
    return False, redirect("courses:detail", slug=course.slug)
