import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment
from apps.courses.models import Course
from apps.dashboard.forms_teacher import TeacherAssignmentForm

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
def teacher_assignment_create_view(request, slug):
    """
    Create a new course assignment.
    """
    course = get_object_or_404(Course, slug=slug)

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
                _("Assignment '%(title)s' created successfully.") % {"title": assignment.title},
            )
            return redirect("dashboard:teacher_course_assignments", slug=course.slug)
    else:
        form = TeacherAssignmentForm(course=course)

    context = {
        "form": form,
        "course": course,
        "is_create": True,
    }
    return render(request, "dashboard/assignments/assignment_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
def teacher_assignment_edit_view(request, slug, assignment_id):
    """
    Edit an existing assignment with submission protections.
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
            return redirect("dashboard:teacher_course_assignments", slug=course.slug)
    else:
        form = TeacherAssignmentForm(instance=assignment, course=course)

    context = {
        "form": form,
        "course": course,
        "assignment": assignment,
        "is_create": False,
        "submissions_count": submissions_count,
    }
    return render(request, "dashboard/assignments/assignment_form.html", context)


@teacher_required
@require_http_methods(["POST"])
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


@teacher_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="30/m", block=True)
def teacher_assignment_delete_view(request, slug, assignment_id):
    """
    Delete an assignment only if no student submissions exist.
    If submissions exist, deletion is blocked and unpublishing is offered.
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

    assign_title = assignment.title
    assignment.delete()
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
