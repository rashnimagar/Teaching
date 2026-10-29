import logging

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment, AssignmentAttachment
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.courses.models import Course
from apps.dashboard.forms_teacher import (
    TeacherAssignmentAttachmentForm,
    TeacherAssignmentForm,
)

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET"])
def teacher_assignments_list_view(request, slug):
    """
    List all assignments for a course with submission counts,
    grading status, Kathmandu deadlines, and draft/published flags.
    """
    course = get_object_or_404(Course, slug=slug)

    # Annotated query to count submissions and ungraded submissions in 1 query
    assignments = list(
        course.assignments.select_related("lesson")
        .annotate(
            total_submissions=Count("submissions"),
            ungraded_submissions=Count("submissions", filter=Q(submissions__grade__isnull=True)),
            graded_submissions=Count("submissions", filter=Q(submissions__grade__isnull=False)),
            attachment_count=Count("attachments"),
        )
        .order_by("-due_at")
    )

    context = {
        "course": course,
        "assignments": assignments,
    }
    return render(request, "dashboard/assignments/assignment_list.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_assignment_create_view(request, slug):
    """
    Create a new course assignment.
    Pre-selects a lesson if passed via ?lesson=<id>.
    Redirects to the edit page after save so attachments can be managed immediately.
    """
    course = get_object_or_404(Course, slug=slug)

    initial = {}
    lesson_id = request.GET.get("lesson")
    if lesson_id:
        try:
            if course.lessons.filter(id=lesson_id).exists():
                initial["lesson"] = lesson_id
        except (ValueError, TypeError):
            pass

    if request.method == "POST":
        form = TeacherAssignmentForm(request.POST, course=course)
        if form.is_valid():
            assignment = form.save()
            logger.info(
                "Teacher %s created assignment '%s' in course %s (ID %s)",
                request.user.id,
                assignment.title,
                course.slug,
                assignment.id,
            )
            messages.success(
                request,
                _(
                    "Assignment '%(title)s' created successfully. You can now manage attachments below."
                )
                % {"title": assignment.title},
            )
            return redirect(
                "dashboard:teacher_course_assignment_edit",
                slug=course.slug,
                assignment_id=assignment.id,
            )
    else:
        form = TeacherAssignmentForm(course=course, initial=initial)

    context = {
        "form": form,
        "course": course,
        "assignment": None,
        "is_create": True,
        "submission_count": 0,
        "submissions_count": 0,
    }
    return render(request, "dashboard/assignments/assignment_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_assignment_edit_view(request, slug, assignment_id):
    """
    Edit an existing assignment with submission protections and attachments manager.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)

    submissions_count = assignment.submissions.count()
    was_published = assignment.is_published

    if request.method == "POST":
        old_max_score = assignment.max_score
        form = TeacherAssignmentForm(request.POST, instance=assignment, course=course)
        if form.is_valid():
            updated_assignment = form.save()

            if was_published and not updated_assignment.is_published:
                logger.info(
                    "Teacher %s unpublished assignment %s (ID %s) affecting %s student submissions",
                    request.user.id,
                    updated_assignment.title,
                    updated_assignment.id,
                    submissions_count,
                )

            # Warning when raising max_score on an assignment that has grades (Requirement 14 / Item 4)
            if updated_assignment.max_score > old_max_score:
                graded_count = updated_assignment.submissions.filter(grade__isnull=False).count()
                if graded_count > 0:
                    messages.warning(
                        request,
                        _(
                            "Warning: Maximum score was raised from %(old)s to %(new)s on an assignment with %(count)s graded submission(s). "
                            "Existing student percentage calculations and grades may need to be reviewed."
                        )
                        % {
                            "old": old_max_score,
                            "new": updated_assignment.max_score,
                            "count": graded_count,
                        },
                    )

            messages.success(
                request,
                _("Assignment '%(title)s' updated successfully.")
                % {"title": updated_assignment.title},
            )
            return redirect(
                "dashboard:teacher_course_assignment_edit",
                slug=course.slug,
                assignment_id=assignment.id,
            )
    else:
        form = TeacherAssignmentForm(instance=assignment, course=course)

    attachments = (
        assignment.attachments.all()
        .annotate(download_count=Count("downloads"))
        .order_by("order", "id")
    )
    attachment_form = TeacherAssignmentAttachmentForm(assignment=assignment)

    context = {
        "form": form,
        "course": course,
        "assignment": assignment,
        "is_create": False,
        "submission_count": submissions_count,
        "submissions_count": submissions_count,
        "attachments": attachments,
        "attachment_form": attachment_form,
    }
    return render(request, "dashboard/assignments/assignment_form.html", context)


@require_POST
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_assignment_attachment_add_view(request, slug, assignment_id):
    """
    Upload and attach a new handout, rubric, or starter file to an assignment.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)

    form = TeacherAssignmentAttachmentForm(request.POST, request.FILES, assignment=assignment)
    if form.is_valid():
        with transaction.atomic():
            max_order = assignment.attachments.aggregate(m=Max("order"))["m"] or 0
            attachment = form.save(commit=False)
            attachment.assignment = assignment
            attachment.order = max_order + 1
            attachment.save()
        messages.success(
            request,
            _("Attachment '%(title)s' added successfully.") % {"title": attachment.title},
        )
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)

    return redirect(
        "dashboard:teacher_course_assignment_edit", slug=course.slug, assignment_id=assignment.id
    )


@require_POST
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_assignment_attachment_edit_view(request, slug, assignment_id, attachment_id):
    """
    Rename, change download policy, or replace an attachment's file.
    Replacing a file keeps download history (Requirement 12) and cleans old file after commit.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    attachment = get_object_or_404(AssignmentAttachment, pk=attachment_id, assignment=assignment)

    old_file_storage = None
    old_file_name = None
    if "file" in request.FILES and attachment.file and attachment.file.name:
        old_file_storage = attachment.file.storage
        old_file_name = attachment.file.name

    form = TeacherAssignmentAttachmentForm(
        request.POST, request.FILES, instance=attachment, assignment=assignment
    )
    if form.is_valid():
        with transaction.atomic():
            form.save()
            if old_file_storage and old_file_name:

                def _cleanup():
                    try:
                        old_file_storage.delete(old_file_name)
                    except (FileNotFoundError, OSError):
                        pass

                transaction.on_commit(_cleanup)

        messages.success(
            request,
            _("Attachment '%(title)s' updated successfully.") % {"title": attachment.title},
        )
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)

    return redirect(
        "dashboard:teacher_course_assignment_edit", slug=course.slug, assignment_id=assignment.id
    )


@require_POST
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_assignment_attachment_toggle_publish_view(request, slug, assignment_id, attachment_id):
    """
    Toggle visibility (published / hidden) of an assignment attachment.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    attachment = get_object_or_404(AssignmentAttachment, pk=attachment_id, assignment=assignment)

    attachment.is_published = not attachment.is_published
    attachment.save(update_fields=["is_published", "updated_at"])

    status = _("published") if attachment.is_published else _("hidden")
    messages.success(
        request,
        _("Attachment '%(title)s' is now %(status)s.")
        % {"title": attachment.title, "status": status},
    )
    return redirect(
        "dashboard:teacher_course_assignment_edit", slug=course.slug, assignment_id=assignment.id
    )


@require_POST
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_assignment_attachment_reorder_view(request, slug, assignment_id, attachment_id):
    """
    Atomic reordering of attachments within an assignment.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    attachment = get_object_or_404(AssignmentAttachment, pk=attachment_id, assignment=assignment)

    direction = request.POST.get("direction")
    attachments = list(assignment.attachments.all().order_by("order", "id"))

    current_idx = None
    for idx, att in enumerate(attachments):
        if att.id == attachment.id:
            current_idx = idx
            break

    if current_idx is not None:
        target_idx = None
        if direction == "up" and current_idx > 0:
            target_idx = current_idx - 1
        elif direction == "down" and current_idx < len(attachments) - 1:
            target_idx = current_idx + 1

        if target_idx is not None:
            other = attachments[target_idx]
            with transaction.atomic():
                cur_order = attachment.order
                attachment.order = other.order
                other.order = cur_order
                attachment.save(update_fields=["order", "updated_at"])
                other.save(update_fields=["order", "updated_at"])

    return redirect(
        "dashboard:teacher_course_assignment_edit", slug=course.slug, assignment_id=assignment.id
    )


@require_POST
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_assignment_attachment_delete_view(request, slug, assignment_id, attachment_id):
    """
    Delete an attachment.
    If students have already downloaded it, it is soft-hidden instead of deleted
    to preserve audit history.
    If no downloads exist, it is deleted from the DB and storage cleaned up after commit.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    attachment = get_object_or_404(AssignmentAttachment, pk=attachment_id, assignment=assignment)

    att_title = attachment.title
    if attachment.downloads.exists():
        attachment.is_published = False
        attachment.save(update_fields=["is_published", "updated_at"])
        messages.info(
            request,
            _(
                "Attachment '%(title)s' was previously downloaded by students. "
                "It has been hidden from students instead of permanently deleted to preserve download audit history."
            )
            % {"title": att_title},
        )
    else:
        storage = attachment.file.storage if attachment.file else None
        file_name = attachment.file.name if attachment.file else None
        with transaction.atomic():
            attachment.delete()
            if storage and file_name:

                def _cleanup():
                    try:
                        storage.delete(file_name)
                    except (FileNotFoundError, OSError):
                        pass

                transaction.on_commit(_cleanup)

        messages.success(
            request, _("Attachment '%(title)s' deleted successfully.") % {"title": att_title}
        )

    return redirect(
        "dashboard:teacher_course_assignment_edit", slug=course.slug, assignment_id=assignment.id
    )


@teacher_required
@require_http_methods(["GET"])
def teacher_assignment_attachment_downloads_view(request, slug, assignment_id, attachment_id):
    """
    View download audit records for an attachment.
    Teachers see student identity and download timestamp without IP addresses (Requirement 5).
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    attachment = get_object_or_404(AssignmentAttachment, pk=attachment_id, assignment=assignment)

    downloads = attachment.downloads.select_related("student").order_by("-downloaded_at")

    context = {
        "course": course,
        "assignment": assignment,
        "attachment": attachment,
        "downloads": downloads,
    }
    return render(request, "dashboard/assignments/attachment_downloads.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_assignment_toggle_publish_view(request, slug, assignment_id):
    """
    Toggle assignment published status.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)

    assignment.is_published = not assignment.is_published
    assignment.save(update_fields=["is_published", "updated_at"])

    status_str = "published" if assignment.is_published else "hidden as draft"
    logger.info(
        "Teacher %s toggled assignment %s (ID %s) to %s",
        request.user.id,
        assignment.title,
        assignment.id,
        status_str,
    )

    messages.success(
        request,
        _("Assignment '%(title)s' is now %(status)s.")
        % {
            "title": assignment.title,
            "status": _("published") if assignment.is_published else _("hidden as draft"),
        },
    )
    return redirect("dashboard:teacher_course_assignments", slug=course.slug)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_assignment_delete_view(request, slug, assignment_id):
    """
    Delete an assignment only if no student submissions exist.
    If submissions exist, deletion is blocked and unpublishing is offered.
    If attachments exist, delete them first with file cleanup after commit to prevent ProtectedError.
    """
    course = get_object_or_404(Course, slug=slug)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)

    submissions_count = assignment.submissions.count()
    if submissions_count > 0:
        logger.warning(
            "Teacher %s attempted to delete assignment '%s' (ID %s) but was blocked due to %s existing submissions",
            request.user.id,
            assignment.title,
            assignment.id,
            submissions_count,
        )
        messages.error(
            request,
            _(
                "Cannot delete assignment '%(title)s' because %(count)s student submission(s) exist. You can unpublish it to hide it from students."
            )
            % {"title": assignment.title, "count": submissions_count},
        )
        return redirect("dashboard:teacher_course_assignments", slug=course.slug)

    files_to_delete = []
    for att in assignment.attachments.all():
        if att.file and att.file.name:
            files_to_delete.append((att.file.storage, att.file.name))

    assign_title = assignment.title
    with transaction.atomic():
        assignment.attachments.all().delete()
        assignment.delete()
        if files_to_delete:

            def _cleanup():
                for storage, filename in files_to_delete:
                    try:
                        storage.delete(filename)
                    except (FileNotFoundError, OSError):
                        pass

            transaction.on_commit(_cleanup)

    logger.info(
        "Teacher %s deleted assignment '%s' (ID %s) from course %s",
        request.user.id,
        assign_title,
        assignment_id,
        course.slug,
    )
    messages.success(
        request, _("Assignment '%(title)s' deleted successfully.") % {"title": assign_title}
    )
    return redirect("dashboard:teacher_course_assignments", slug=course.slug)
