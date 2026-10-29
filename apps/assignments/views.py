import logging
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import is_teacher_user
from apps.assignments.models import (
    Assignment,
    AssignmentAttachment,
    AssignmentAttachmentDownload,
    Submission,
    SubmissionEvent,
)
from apps.assignments.permissions import check_assignment_access
from apps.assignments.status import get_assignment_status
from apps.assignments.validators import (
    sanitize_display_filename,
    validate_submission_file,
)
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.core.utils import get_client_ip
from apps.courses.models import Course

logger = logging.getLogger(__name__)


def _safe_delete_storage_file(storage, file_name: str) -> None:
    """Safely delete a file from private storage without raising on missing files."""
    if storage and file_name:
        try:
            storage.delete(file_name)
        except (FileNotFoundError, OSError):
            pass


@require_http_methods(["GET"])
def course_assignments_view(request, slug):
    """
    Overview list of all assignments for an active course.
    Shows status badges, deadlines in Asia/Kathmandu, live countdown data,
    and a summary card with points earned / max points of graded assignments.
    """
    course = get_object_or_404(Course, slug=slug)
    is_allowed, redirect_resp = check_assignment_access(request, course)
    if not is_allowed:
        return redirect_resp

    now = timezone.now()
    is_teacher = is_teacher_user(request.user)

    # Load assignments for the course with lessons
    assign_qs = course.assignments.all()
    if not is_teacher:
        assign_qs = assign_qs.filter(is_published=True).filter(
            Q(lesson__isnull=True) | Q(lesson__is_published=True)
        )
    assignments = list(assign_qs.select_related("lesson").order_by("due_at", "id"))

    # Load current student's submissions
    submissions_dict = {}
    if request.user.is_authenticated:
        sub_qs = Submission.objects.filter(
            assignment__course=course,
            student=request.user,
        )
        if not is_teacher:
            sub_qs = sub_qs.filter(
                assignment__is_published=True,
            ).filter(Q(assignment__lesson__isnull=True) | Q(assignment__lesson__is_published=True))
        student_submissions = sub_qs.select_related("assignment")
        submissions_dict = {sub.assignment_id: sub for sub in student_submissions}

    # Format assignment cards
    assignment_items = []
    for assign in assignments:
        submission = submissions_dict.get(assign.id)
        status_info = get_assignment_status(assign, submission, now=now)

        # Requirement 2: Before opens_at, hide instructions and linked unpublished lesson
        if now < assign.opens_at and not is_teacher:
            display_instructions = ""
            linked_lesson = None
        else:
            display_instructions = assign.instructions
            if assign.lesson:
                linked_lesson = (
                    assign.lesson if (assign.lesson.is_published or is_teacher) else None
                )
            else:
                linked_lesson = None

        assignment_items.append(
            {
                "assignment": assign,
                "submission": submission,
                "status": status_info,
                "instructions": display_instructions,
                "linked_lesson": linked_lesson,
                "is_not_open": now < assign.opens_at,
            }
        )

    # Requirement 18: Overall score = points earned / max points of graded assignments only
    graded_submissions = [s for s in submissions_dict.values() if s and s.grade is not None]
    submitted_count = len(submissions_dict)
    graded_count = len(graded_submissions)

    earned_points = sum(s.grade for s in graded_submissions)
    graded_max_points = sum(s.assignment.max_score for s in graded_submissions)
    if graded_max_points > 0:
        overall_percentage = round((float(earned_points) / float(graded_max_points)) * 100, 1)
    else:
        overall_percentage = None

    context = {
        "course": course,
        "assignments": assignment_items,
        "total_count": len(assignments),
        "submitted_count": submitted_count,
        "graded_count": graded_count,
        "earned_points": earned_points,
        "graded_max_points": graded_max_points,
        "overall_percentage": overall_percentage,
        "server_time_iso": now.isoformat(),
    }
    return render(request, "assignments/assignment_list.html", context)


@ratelimit(key="user", rate="10/m", block=True, method=["POST"])
@ratelimit(key="user", rate="30/h", block=True, method=["POST"])
@require_http_methods(["GET", "POST"])
def assignment_detail_view(request, slug, assignment_id):
    """
    Assignment detail and student submission view.
    GET: Displays instructions, deadline, status badge, grade card, and form.
    POST: Processes student submission with PostgreSQL-compatible select_for_update() row locking,
          atomic deadline validation, file replacement with transaction.on_commit, and double-submit protection.
    """
    course = get_object_or_404(Course, slug=slug)
    is_allowed, redirect_resp = check_assignment_access(request, course)
    if not is_allowed:
        return redirect_resp

    assignment = get_object_or_404(
        Assignment.objects.select_related("course", "lesson"),
        pk=assignment_id,
        course=course,
    )

    is_teacher = is_teacher_user(request.user)
    if not is_teacher:
        if not assignment.is_published:
            raise Http404(_("Assignment not found."))
        if assignment.lesson and not assignment.lesson.is_published:
            raise Http404(_("Assignment not found."))

    now = timezone.now()

    # Load existing submission if any
    submission = None
    if request.user.is_authenticated:
        submission = Submission.objects.filter(
            assignment=assignment,
            student=request.user,
        ).first()

    status_info = get_assignment_status(assignment, submission, now=now)

    # Requirement 2: Before opens_at, show only title and opening time;
    # hide instructions and any linked unpublished lesson title server-side.
    is_not_open = now < assignment.opens_at
    if is_not_open and not is_teacher:
        display_instructions = ""
        linked_lesson = None
    else:
        display_instructions = assignment.instructions
        if assignment.lesson:
            linked_lesson = (
                assignment.lesson if (assignment.lesson.is_published or is_teacher) else None
            )
        else:
            linked_lesson = None

    # Handle POST Submission
    if request.method == "POST":
        # Anonymous users cannot submit
        if not request.user.is_authenticated:
            raise PermissionDenied(_("You must be logged in to submit an assignment."))

        # Requirement 1: Lock editing once a submission is graded unless explicitly unlocked by teacher
        if submission and submission.grade is not None and not submission.is_unlocked:
            messages.error(
                request, _("This submission has already been graded and can no longer be edited.")
            )
            return redirect("assignments:detail", slug=course.slug, assignment_id=assignment.id)

        content_text = request.POST.get("content_text", "").strip()
        uploaded_file = request.FILES.get("file")

        # Text length validation (Requirement 12)
        max_text_len = getattr(settings, "ASSIGNMENT_MAX_TEXT_LENGTH", 20000)
        if len(content_text) > max_text_len:
            form_error = _(
                "Written response exceeds the maximum allowed length of %(max_len)s characters."
            ) % {"max_len": max_text_len}
            return _render_detail(
                request,
                course,
                assignment,
                submission,
                status_info,
                display_instructions,
                linked_lesson,
                is_not_open,
                form_error=form_error,
                typed_text=content_text,
                status_code=400,
            )

        # Require at least text or file (or retain existing file)
        has_existing_file = bool(submission and submission.file)
        if not content_text and not uploaded_file and not has_existing_file:
            form_error = _("You must provide either a written response or an attached file.")
            return _render_detail(
                request,
                course,
                assignment,
                submission,
                status_info,
                display_instructions,
                linked_lesson,
                is_not_open,
                form_error=form_error,
                typed_text=content_text,
                status_code=400,
            )

        # File validation if newly attached
        sanitized_filename = ""
        if uploaded_file:
            try:
                validate_submission_file(uploaded_file)
                sanitized_filename = sanitize_display_filename(uploaded_file.name)
            except ValidationError as exc:
                err_msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
                return _render_detail(
                    request,
                    course,
                    assignment,
                    submission,
                    status_info,
                    display_instructions,
                    linked_lesson,
                    is_not_open,
                    form_error=err_msg,
                    typed_text=content_text,
                    status_code=400,
                )

        new_file_saved = None

        try:
            with transaction.atomic():
                # Requirement 4: select_for_update locking assignment row for race-safe deadline comparison
                locked_assignment = Assignment.objects.select_for_update().get(
                    pk=assignment.id, course=course
                )
                # Also lock existing submission row (if any) to prevent concurrent double-update race
                locked_submission = (
                    Submission.objects.select_for_update()
                    .filter(assignment=locked_assignment, student=request.user)
                    .first()
                )
                is_unlocked_resubmission = bool(locked_submission and locked_submission.is_unlocked)

                if (
                    locked_submission
                    and locked_submission.grade is not None
                    and not is_unlocked_resubmission
                ):
                    messages.error(
                        request,
                        _("This submission has already been graded and cannot be modified."),
                    )
                    return redirect(
                        "assignments:detail", slug=course.slug, assignment_id=assignment.id
                    )

                current_now = timezone.now()

                # Opening time boundary check
                if current_now < locked_assignment.opens_at:
                    form_error = _("This assignment has not opened for submissions yet.")
                    return _render_detail(
                        request,
                        course,
                        locked_assignment,
                        locked_submission,
                        status_info,
                        display_instructions,
                        linked_lesson,
                        is_not_open,
                        form_error=form_error,
                        typed_text=content_text,
                        status_code=400,
                    )

                # Deadline boundary check (overridden if unlocked by teacher)
                if (
                    current_now > locked_assignment.due_at
                    and not locked_assignment.allow_late
                    and not is_unlocked_resubmission
                ):
                    form_error = _("The deadline has passed and late submissions are not accepted.")
                    return _render_detail(
                        request,
                        course,
                        locked_assignment,
                        locked_submission,
                        status_info,
                        display_instructions,
                        linked_lesson,
                        is_not_open,
                        form_error=form_error,
                        typed_text=content_text,
                        status_code=400,
                    )

                # Requirement 1: submitted_at and is_late use one now() value;
                # with allow_late, is_late follows the latest save.
                is_late = current_now > locked_assignment.due_at

                target_sub = locked_submission or Submission(
                    assignment=locked_assignment,
                    student=request.user,
                )
                target_sub.content_text = content_text
                target_sub.submitted_at = current_now
                target_sub.is_late = is_late

                # When resubmitting an unlocked submission, reset grade so it appears in the teacher's grading queue
                old_grade = target_sub.grade
                if is_unlocked_resubmission:
                    target_sub.grade = None
                    target_sub.graded_by = None
                    target_sub.graded_at = None
                    target_sub.is_unlocked = False

                old_file_name = None
                old_storage = None

                if uploaded_file:
                    if target_sub.file and target_sub.file.name:
                        old_file_name = target_sub.file.name
                        old_storage = target_sub.file.storage

                    # Requirement 3: Save new file to storage FIRST
                    target_sub.file.save(uploaded_file.name, uploaded_file, save=False)
                    target_sub.original_filename = sanitized_filename
                    new_file_saved = target_sub.file

                # Persist submission to DB
                target_sub.save()

                if is_unlocked_resubmission:
                    SubmissionEvent.objects.create(
                        submission=target_sub,
                        actor=request.user,
                        action="resubmitted",
                        old_grade=old_grade,
                        new_grade=None,
                        note=_("Student resubmitted updated work after submission was unlocked."),
                    )

                if uploaded_file and old_file_name:
                    if old_file_name != target_sub.file.name:
                        # Requirement 3: delete old file in transaction.on_commit
                        transaction.on_commit(
                            lambda name=old_file_name, storage=old_storage: (
                                _safe_delete_storage_file(storage, name)
                            )
                        )

            messages.success(
                request,
                _("Your assignment submission has been successfully received.")
                if not is_late
                else _("Your late assignment submission has been received."),
            )
            return redirect("assignments:detail", slug=course.slug, assignment_id=assignment.id)

        except Exception as exc:
            # Requirement 3: If rejected or rolled back after a file was stored, delete the newly stored file
            if new_file_saved:
                _safe_delete_storage_file(new_file_saved.storage, new_file_saved.name)
            logger.exception("Error saving assignment submission: %s", exc)
            raise

    # GET Request: render detail page
    return _render_detail(
        request,
        course,
        assignment,
        submission,
        status_info,
        display_instructions,
        linked_lesson,
        is_not_open,
    )


def _render_detail(
    request,
    course,
    assignment,
    submission,
    status_info,
    display_instructions,
    linked_lesson,
    is_not_open,
    form_error=None,
    typed_text=None,
    status_code=200,
):
    """Helper to render the assignment detail template with all required context."""
    initial_text = (
        typed_text if typed_text is not None else (submission.content_text if submission else "")
    )
    can_submit = (
        not is_not_open
        and (not submission or submission.grade is None or submission.is_unlocked)
        and (timezone.now() <= assignment.due_at or assignment.allow_late)
    ) or bool(form_error)

    is_teacher = is_teacher_user(request.user)
    if is_not_open and not is_teacher:
        attachments = []
    else:
        att_qs = assignment.attachments.all()
        if not is_teacher:
            att_qs = att_qs.filter(is_published=True)
        attachments = list(att_qs.order_by("order", "id"))

    context = {
        "course": course,
        "assignment": assignment,
        "submission": submission,
        "status": status_info,
        "instructions": display_instructions,
        "linked_lesson": linked_lesson,
        "is_not_open": is_not_open,
        "can_submit": can_submit,
        "initial_text": initial_text,
        "form_error": form_error,
        "attachments": attachments,
        "server_time_iso": timezone.now().isoformat(),
        "max_text_len": getattr(settings, "ASSIGNMENT_MAX_TEXT_LENGTH", 20000),
    }
    return render(request, "assignments/assignment_detail.html", context, status=status_code)


@require_http_methods(["GET"])
@ratelimit(key="user", rate="60/m", block=True)
def submission_download_view(request, slug, submission_id):
    """
    Permission-checked file download route by submission ID (Requirement 6).
    Allowed for the submitting student and staff only.
    Returns FileResponse with Content-Type: application/octet-stream,
    X-Content-Type-Options: nosniff, Cache-Control: private, no-store (Requirement 7).
    """
    course = get_object_or_404(Course, slug=slug)
    if not request.user.is_authenticated:
        login_url = f"{resolve_url(settings.LOGIN_URL)}?next={request.path}"
        return redirect(login_url)
    is_allowed, redirect_resp = check_assignment_access(request, course, is_api=True)
    if not is_allowed:
        return redirect_resp

    submission = get_object_or_404(
        Submission.objects.select_related("assignment__course", "assignment__lesson", "student"),
        pk=submission_id,
        assignment__course=course,
    )

    # Permission check: submitting student or teacher/staff
    if not (is_teacher_user(request.user) or submission.student == request.user):
        return HttpResponseForbidden(
            _("You do not have permission to download this submission file.")
        )

    if not is_teacher_user(request.user):
        if not submission.assignment.is_published:
            raise Http404(_("Assignment not found."))
        if submission.assignment.lesson and not submission.assignment.lesson.is_published:
            raise Http404(_("Assignment not found."))

    if not submission.file:
        raise Http404(_("No file is attached to this submission."))

    filename = (
        submission.original_filename
        or f"submission_{submission.id}{Path(submission.file.name).suffix}"
    )

    try:
        file_obj = submission.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404(_("The submission file could not be located on storage.")) from None

    response = FileResponse(
        file_obj,
        as_attachment=True,
        filename=filename,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET"])
@ratelimit(key="user", rate="60/m", block=True)
def attachment_download_view(request, slug, attachment_id):
    """
    Permission-checked download endpoint for assignment attachments.
    Re-checks enrollment, published status, opening time, and view-only policy.
    Audits downloads in AssignmentAttachmentDownload via trusted proxy helper.
    """
    course = get_object_or_404(Course, slug=slug)
    if not request.user.is_authenticated:
        login_url = f"{resolve_url(settings.LOGIN_URL)}?next={request.path}"
        return redirect(login_url)

    is_allowed, redirect_resp = check_assignment_access(request, course, is_api=True)
    if not is_allowed:
        return redirect_resp

    attachment = get_object_or_404(
        AssignmentAttachment.objects.select_related("assignment__course", "assignment__lesson"),
        pk=attachment_id,
        assignment__course=course,
    )
    assignment = attachment.assignment

    is_staff = is_teacher_user(request.user)

    if not is_staff:
        if not assignment.is_published or not attachment.is_published:
            raise Http404(_("Attachment not found."))
        if assignment.lesson and not assignment.lesson.is_published:
            raise Http404(_("Attachment not found."))
        if timezone.now() < assignment.opens_at:
            raise Http404(_("Attachment not available yet."))
        if attachment.download_policy == AssignmentAttachment.DownloadPolicy.VIEW_ONLY:
            return HttpResponseForbidden(
                _("This attachment is marked as view-only and cannot be downloaded.")
            )

    if not attachment.file or not attachment.file.name:
        raise Http404(_("Attachment file could not be located."))

    # Log download if authenticated student (staff downloads are not audited as student downloads)
    if request.user.is_authenticated and not is_staff:
        client_ip = get_client_ip(None, request)
        AssignmentAttachmentDownload.objects.create(
            attachment=attachment,
            student=request.user,
            downloaded_at=timezone.now(),
            ip_address=client_ip,
        )

    filename = (
        attachment.original_filename
        or f"attachment_{attachment.id}{Path(attachment.file.name).suffix}"
    )

    try:
        file_obj = attachment.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404(_("The attachment file could not be located on storage.")) from None

    response = FileResponse(
        file_obj,
        as_attachment=True,
        filename=filename,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET"])
@xframe_options_sameorigin
@ratelimit(key="user", rate="60/m", block=True)
def attachment_preview_view(request, slug, attachment_id):
    """
    Inline browser preview endpoint for PDF and image attachments.
    Uses isolated-frame pattern: SAMEORIGIN, frame-ancestors 'self', nosniff, Cache-Control private no-store.
    No CSP sandbox applied so Chrome PDF viewer can render properly.
    """
    course = get_object_or_404(Course, slug=slug)
    if not request.user.is_authenticated:
        login_url = f"{resolve_url(settings.LOGIN_URL)}?next={request.path}"
        return redirect(login_url)

    is_allowed, redirect_resp = check_assignment_access(request, course, is_api=True)
    if not is_allowed:
        return redirect_resp

    attachment = get_object_or_404(
        AssignmentAttachment.objects.select_related("assignment__course", "assignment__lesson"),
        pk=attachment_id,
        assignment__course=course,
    )
    assignment = attachment.assignment

    is_staff = is_teacher_user(request.user)

    if not is_staff:
        if not assignment.is_published or not attachment.is_published:
            raise Http404(_("Attachment not found."))
        if assignment.lesson and not assignment.lesson.is_published:
            raise Http404(_("Attachment not found."))
        if timezone.now() < assignment.opens_at:
            raise Http404(_("Attachment not available yet."))

    PREVIEW_MIME_TYPES = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    ext = (attachment.file_extension or "").lower().lstrip(".")
    content_type = PREVIEW_MIME_TYPES.get(ext)
    if not content_type:
        return HttpResponseForbidden(_("Unsupported preview format."))

    if not attachment.file or not attachment.file.name:
        raise Http404(_("Attachment file could not be located."))

    try:
        file_obj = attachment.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404(_("The attachment file could not be located on storage.")) from None

    response = FileResponse(
        file_obj,
        as_attachment=False,
        content_type=content_type,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "SAMEORIGIN"
    response._csp_replace = {
        "frame-ancestors": ["'self'"],
    }
    response._csp_update = {
        "frame-src": ["'self'"],
    }
    return response
