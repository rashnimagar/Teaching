from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, resolve_url
from django.utils.translation import gettext_lazy as _

from apps.courses.models import Course, Enrollment, Lesson


def check_lesson_access(
    request, course: Course, lesson: Lesson | None = None, is_api: bool = False
):
    """
    Enforces server-side access control for course learning views and progress endpoints.

    Rules:
    - Unpublished courses return 404 for non-staff.
    - Archived courses return 404 for non-staff UNLESS the student has an ACTIVE enrollment.
    - Unpublished lessons return 404 for non-staff.
    - Teachers and staff have unrestricted access to all courses and lessons.
    - Anonymous users are redirected to login (or 403 in API mode).
    - Preview lessons (is_preview=True) are accessible to any authenticated user.
    - Active enrollment grants full access to published lessons.
    - Pending or revoked enrollments, or non-enrolled users, are blocked:
        - In page views: redirected to course detail with a friendly message.
        - In API endpoints: returned 403 Forbidden.

    Returns:
        tuple[bool, HttpResponse | None]: (is_allowed, response_if_blocked)
    """
    # 1. Unpublished course check
    if not course.is_published:
        if not (request.user.is_authenticated and request.user.is_staff):
            raise Http404(_("Course not found."))

    # 2. Archived course check: only active enrollments or staff retain access
    if course.is_archived:
        if request.user.is_authenticated:
            is_active_student = Enrollment.objects.filter(
                student=request.user, course=course, status=Enrollment.Status.ACTIVE
            ).exists()
            if not (request.user.is_staff or is_active_student):
                raise Http404(_("Course not found."))
        else:
            raise Http404(_("Course not found."))

    # 3. Unpublished lesson check
    if lesson is not None and not lesson.is_published:
        if not (request.user.is_authenticated and request.user.is_staff):
            raise Http404(_("Lesson not found."))

    # 4. Teacher / Staff bypass
    if request.user.is_authenticated and request.user.is_staff:
        return True, None

    # 5. Anonymous user
    if not request.user.is_authenticated:
        if is_api:
            return False, HttpResponseForbidden(_("Authentication required."))
        login_url = f"{resolve_url(settings.LOGIN_URL)}?next={request.path}"
        return False, redirect(login_url)

    # 6. Preview lesson access for any logged-in user
    if lesson is not None and lesson.is_preview:
        return True, None

    # 7. Student enrollment verification
    enrollment = Enrollment.objects.filter(student=request.user, course=course).first()

    if not enrollment:
        if is_api:
            return False, HttpResponseForbidden(_("Enrollment required to access this lesson."))
        messages.info(request, _("Please enroll in this course to access lessons."))
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


def check_material_access(request, course: Course, material=None, is_api: bool = False):
    """
    Enforces server-side access control for course materials.

    Rules:
    - Unpublished courses return 404 for non-staff.
    - Archived courses return 404 for non-staff UNLESS the student has an ACTIVE enrollment.
    - Unpublished or archived materials return 404 for non-staff.
    - Teachers and staff have unrestricted access.
    - Anonymous users are redirected to login (or 403 in API mode).
    - Active enrollment grants access to materials.
    - Pending, revoked, or non-enrolled students are blocked.
    """
    # 1. Unpublished course check
    if not course.is_published:
        if not (
            request.user.is_authenticated
            and (request.user.is_staff or getattr(request.user, "is_teacher", False))
        ):
            raise Http404(_("Course not found."))

    # 2. Archived course check
    if course.is_archived:
        if request.user.is_authenticated:
            is_active_student = Enrollment.objects.filter(
                student=request.user, course=course, status=Enrollment.Status.ACTIVE
            ).exists()
            if not (
                request.user.is_staff
                or getattr(request.user, "is_teacher", False)
                or is_active_student
            ):
                raise Http404(_("Course not found."))
        else:
            raise Http404(_("Course not found."))

    # 3. Material visibility
    if material is not None:
        if not material.is_published or material.is_archived:
            if not (
                request.user.is_authenticated
                and (request.user.is_staff or getattr(request.user, "is_teacher", False))
            ):
                raise Http404(_("Material not found."))

    # 4. Teacher / Staff bypass
    if request.user.is_authenticated and (
        request.user.is_staff or getattr(request.user, "is_teacher", False)
    ):
        return True, None

    # 5. Anonymous user
    if not request.user.is_authenticated:
        if is_api:
            return False, HttpResponseForbidden(_("Authentication required."))
        login_url = f"{resolve_url(settings.LOGIN_URL)}?next={request.path}"
        return False, redirect(login_url)

    # 6. Student enrollment verification
    enrollment = Enrollment.objects.filter(student=request.user, course=course).first()
    if not enrollment or enrollment.status != Enrollment.Status.ACTIVE:
        if is_api:
            return False, HttpResponseForbidden(
                _("Active enrollment required to access materials.")
            )
        messages.info(request, _("Active course enrollment required to access materials."))
        return False, redirect("courses:detail", slug=course.slug)

    return True, None
