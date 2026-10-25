import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.accounts.permissions import teacher_required
from apps.assignments.models import Assignment
from apps.courses.models import Course, Enrollment, Lesson
from apps.dashboard.forms_teacher import TeacherCourseForm

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET"])
def teacher_courses_list_view(request):
    """
    Teacher course list with search, status filters, pricing filters,
    and subquery-based counts for lessons, assignments, and active enrollments.
    """
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "all")
    pricing_filter = request.GET.get("pricing", "all")

    # Subqueries to avoid Cartesian product join multiplication
    lesson_count_subquery = Subquery(
        Lesson.objects.filter(course_id=OuterRef("pk"))
        .values("course_id")
        .annotate(cnt=Count("id"))
        .values("cnt")[:1],
        output_field=models.IntegerField(),
    )
    assignment_count_subquery = Subquery(
        Assignment.objects.filter(course_id=OuterRef("pk"))
        .values("course_id")
        .annotate(cnt=Count("id"))
        .values("cnt")[:1],
        output_field=models.IntegerField(),
    )
    active_student_subquery = Subquery(
        Enrollment.objects.filter(course_id=OuterRef("pk"), status=Enrollment.Status.ACTIVE)
        .values("course_id")
        .annotate(cnt=Count("id"))
        .values("cnt")[:1],
        output_field=models.IntegerField(),
    )

    qs = Course.objects.annotate(
        lesson_count=Coalesce(lesson_count_subquery, 0),
        assignment_count=Coalesce(assignment_count_subquery, 0),
        active_student_count=Coalesce(active_student_subquery, 0),
    ).order_by("-created_at")

    if search_query:
        qs = qs.filter(
            Q(title__icontains=search_query) | Q(short_description__icontains=search_query)
        )

    if status_filter == "published":
        qs = qs.filter(is_published=True, is_archived=False)
    elif status_filter == "draft":
        qs = qs.filter(is_published=False, is_archived=False)
    elif status_filter == "archived":
        qs = qs.filter(is_archived=True)

    if pricing_filter == "free":
        qs = qs.filter(is_free=True)
    elif pricing_filter == "paid":
        qs = qs.filter(is_free=False)

    paginator = Paginator(qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Summary metric counts
    total_courses_count = Course.objects.count()
    published_count = Course.objects.filter(is_published=True, is_archived=False).count()
    draft_count = Course.objects.filter(is_published=False, is_archived=False).count()
    archived_count = Course.objects.filter(is_archived=True).count()

    context = {
        "page_obj": page_obj,
        "courses": page_obj,
        "search_query": search_query,
        "status_filter": status_filter,
        "pricing_filter": pricing_filter,
        "total_courses_count": total_courses_count,
        "published_count": published_count,
        "draft_count": draft_count,
        "archived_count": archived_count,
    }
    return render(request, "dashboard/courses/course_list.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
def teacher_course_create_view(request):
    """
    Create a new course offering.
    """
    if request.method == "POST":
        form = TeacherCourseForm(request.POST, request.FILES)
        if form.is_valid():
            course = form.save()
            logger.info("Teacher %s created course %s (ID %s)", request.user.id, course.slug, course.id)
            messages.success(request, _("Course '%(title)s' created successfully.") % {"title": course.title})
            return redirect("dashboard:teacher_courses")
    else:
        form = TeacherCourseForm()

    context = {
        "form": form,
        "is_create": True,
    }
    return render(request, "dashboard/courses/course_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
def teacher_course_edit_view(request, slug):
    """
    Edit course metadata, pricing, visibility, and approval requirements.
    """
    course = get_object_or_404(Course, slug=slug)
    active_students_count = Enrollment.objects.filter(course=course, status=Enrollment.Status.ACTIVE).count()

    if request.method == "POST":
        form = TeacherCourseForm(request.POST, request.FILES, instance=course)
        was_published = course.is_published
        if form.is_valid():
            course = form.save()
            is_now_published = course.is_published

            if was_published and not is_now_published:
                logger.info(
                    "Teacher %s unpublished course %s (ID %s) affecting %s active students",
                    request.user.id,
                    course.slug,
                    course.id,
                    active_students_count,
                )

            messages.success(request, _("Course '%(title)s' updated successfully.") % {"title": course.title})
            return redirect("dashboard:teacher_courses")
    else:
        form = TeacherCourseForm(instance=course)

    context = {
        "form": form,
        "course": course,
        "is_create": False,
        "active_students_count": active_students_count,
    }
    return render(request, "dashboard/courses/course_form.html", context)


@teacher_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="30/m", block=True)
def teacher_course_archive_view(request, slug):
    """
    Archive or restore a course. If archived, existing enrolled students
    retain access, but the course is hidden from the public catalog.
    No hard deletion of courses is supported in the dashboard.
    """
    course = get_object_or_404(Course, slug=slug)
    action = request.POST.get("action", "archive")

    if action == "archive":
        course.is_archived = True
        course.save(update_fields=["is_archived", "updated_at"])
        logger.info("Teacher %s archived course %s (ID %s)", request.user.id, course.slug, course.id)
        messages.success(
            request,
            _("Course '%(title)s' has been archived. Enrolled students retain access, but it is hidden from the catalog.")
            % {"title": course.title},
        )
    elif action == "restore":
        course.is_archived = False
        course.save(update_fields=["is_archived", "updated_at"])
        logger.info("Teacher %s restored course %s (ID %s)", request.user.id, course.slug, course.id)
        messages.success(request, _("Course '%(title)s' has been restored.") % {"title": course.title})

    return redirect("dashboard:teacher_courses")
