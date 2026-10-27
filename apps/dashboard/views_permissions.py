import logging
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts.permissions import teacher_required
from apps.courses.models import Course, DownloadLog, DownloadRequest, MaterialItem
from apps.courses.services.download_requests import (
    approve_for_all_enrolled,
    transition_download_request,
)

logger = logging.getLogger(__name__)


@teacher_required
def teacher_permissions_view(request):
    """
    Teacher Permissions & Download Requests Queue.
    Allows teachers and staff to inspect, filter, search, approve, deny, revoke,
    and bulk-manage download requests with full student isolation and real-time state tracking.
    """
    status_filter = request.GET.get("status", "all").strip().lower()
    course_filter = request.GET.get("course", "").strip()
    search_query = request.GET.get("q", "").strip()

    # Base queryset with bounded queries
    queryset = (
        DownloadRequest.objects.all()
        .select_related(
            "student",
            "material_item",
            "material_item__material",
            "material_item__material__course",
            "decided_by",
        )
        .order_by("-requested_at")
    )

    # Status counts for header tabs
    all_count = DownloadRequest.objects.count()
    pending_count = DownloadRequest.objects.filter(status=DownloadRequest.Status.PENDING).count()
    approved_count = DownloadRequest.objects.filter(status=DownloadRequest.Status.APPROVED).count()
    denied_count = DownloadRequest.objects.filter(status=DownloadRequest.Status.DENIED).count()
    revoked_count = DownloadRequest.objects.filter(status=DownloadRequest.Status.REVOKED).count()

    # Apply filters
    if status_filter in [
        DownloadRequest.Status.PENDING,
        DownloadRequest.Status.APPROVED,
        DownloadRequest.Status.DENIED,
        DownloadRequest.Status.REVOKED,
    ]:
        queryset = queryset.filter(status=status_filter)

    if course_filter.isdigit():
        queryset = queryset.filter(material_item__material__course_id=int(course_filter))

    if search_query:
        queryset = queryset.filter(
            Q(student__first_name__icontains=search_query)
            | Q(student__last_name__icontains=search_query)
            | Q(student__email__icontains=search_query)
            | Q(material_item__title__icontains=search_query)
            | Q(material_item__material__title__icontains=search_query)
        )

    # Pagination: 25 items per page
    paginator = Paginator(queryset, 25)
    page_number = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Active courses for the course filter dropdown
    courses = Course.objects.all().order_by("title")

    context = {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "course_filter": course_filter,
        "search_query": search_query,
        "courses": courses,
        "all_count": all_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "denied_count": denied_count,
        "revoked_count": revoked_count,
    }
    return render(request, "dashboard/teacher_permissions.html", context)


@teacher_required
@require_POST
@ratelimit(key="user_or_ip", rate="60/m", block=True)
def teacher_permission_action_view(request, request_id):
    """
    Execute state transition on a single DownloadRequest row.
    Guarantees row locking, idempotency, and notifications via transition_download_request.
    """
    req_obj = get_object_or_404(
        DownloadRequest.objects.select_related(
            "student", "material_item", "material_item__material__course"
        ),
        pk=request_id,
    )
    action = request.POST.get("action", "").strip().lower()
    next_url = (
        request.POST.get("next")
        or request.META.get("HTTP_REFERER")
        or "/dashboard/teacher/permissions/"
    )

    if action == "approve":
        # Check for expiry date or days preset
        expiry_days_str = request.POST.get("expiry_days", "").strip()
        custom_expiry_str = request.POST.get("expires_at", "").strip()
        expires_at = None

        if expiry_days_str.isdigit():
            days = int(expiry_days_str)
            if days > 0:
                expires_at = timezone.now() + timedelta(days=days)
        elif custom_expiry_str:
            parsed = parse_datetime(custom_expiry_str)
            if parsed:
                expires_at = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

        _, success, message = transition_download_request(
            request_obj=req_obj,
            new_status=DownloadRequest.Status.APPROVED,
            decided_by=request.user,
            expires_at=expires_at,
        )
        if success:
            messages.success(
                request,
                f"Approved request for {req_obj.student.email} ({req_obj.material_item.title}).",
            )
        else:
            messages.warning(request, message)

    elif action == "deny":
        teacher_note = request.POST.get("teacher_note", "").strip()
        _, success, message = transition_download_request(
            request_obj=req_obj,
            new_status=DownloadRequest.Status.DENIED,
            decided_by=request.user,
            teacher_note=teacher_note,
        )
        if success:
            messages.success(
                request, f"Denied request for {req_obj.student.email} with note recorded."
            )
        else:
            messages.warning(request, message)

    elif action == "revoke":
        _, success, message = transition_download_request(
            request_obj=req_obj,
            new_status=DownloadRequest.Status.REVOKED,
            decided_by=request.user,
        )
        if success:
            messages.success(request, f"Revoked download access for {req_obj.student.email}.")
        else:
            messages.warning(request, message)

    elif action in ("restore", "reconsider"):
        _, success, message = transition_download_request(
            request_obj=req_obj,
            new_status=DownloadRequest.Status.APPROVED,
            decided_by=request.user,
            expires_at=None,
        )
        if success:
            messages.success(request, f"Restored approved access for {req_obj.student.email}.")
        else:
            messages.warning(request, message)

    else:
        messages.error(request, f"Unrecognized action: {action}")

    return redirect(next_url)


@teacher_required
@require_POST
@ratelimit(key="user_or_ip", rate="30/m", block=True)
def teacher_permissions_bulk_action_view(request):
    """
    Bulk state transitions for selected rows on the current page.
    Applies transitions per row, skips invalid rows, and displays summary counts.
    """
    action = request.POST.get("bulk_action", "").strip().lower()
    selected_ids = request.POST.getlist("selected_ids")
    next_url = (
        request.POST.get("next")
        or request.META.get("HTTP_REFERER")
        or "/dashboard/teacher/permissions/"
    )

    if not selected_ids:
        messages.warning(request, "No requests were selected for bulk action.")
        return redirect(next_url)

    # Convert IDs to integers safely
    req_ids = []
    for sid in selected_ids:
        if sid.isdigit():
            req_ids.append(int(sid))

    if not req_ids:
        messages.warning(request, "No valid request IDs were selected.")
        return redirect(next_url)

    reqs = list(
        DownloadRequest.objects.filter(pk__in=req_ids).select_related(
            "student", "material_item", "material_item__material__course"
        )
    )

    success_count = 0
    skipped_count = 0

    if action == "approve":
        expiry_days_str = request.POST.get("bulk_expiry_days", "").strip()
        expires_at = None
        if expiry_days_str.isdigit():
            days = int(expiry_days_str)
            if days > 0:
                expires_at = timezone.now() + timedelta(days=days)

        for req in reqs:
            _, success, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.APPROVED,
                decided_by=request.user,
                expires_at=expires_at,
            )
            if success:
                success_count += 1
            else:
                skipped_count += 1

        messages.success(
            request,
            f"Bulk approval complete: {success_count} approved, {skipped_count} skipped (invalid state or already approved).",
        )

    elif action == "deny":
        teacher_note = request.POST.get("bulk_teacher_note", "").strip()
        for req in reqs:
            _, success, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.DENIED,
                decided_by=request.user,
                teacher_note=teacher_note,
            )
            if success:
                success_count += 1
            else:
                skipped_count += 1

        messages.success(
            request,
            f"Bulk denial complete: {success_count} denied, {skipped_count} skipped.",
        )

    else:
        messages.error(request, f"Unknown bulk action: {action}")

    return redirect(next_url)


@teacher_required
@require_POST
@ratelimit(key="user_or_ip", rate="30/m", block=True)
def teacher_approve_for_all_view(request, item_id):
    """
    Approve for all enrolled students: switches material item download policy
    to open_to_enrolled, resolves all existing pending requests for that item to approved,
    and notifies each student.
    """
    item = get_object_or_404(
        MaterialItem.objects.select_related("material", "material__course"),
        pk=item_id,
    )
    next_url = (
        request.POST.get("next")
        or request.META.get("HTTP_REFERER")
        or "/dashboard/teacher/permissions/"
    )

    resolved, skipped = approve_for_all_enrolled(item, decided_by=request.user)

    messages.success(
        request,
        f"'{item.title}' is now open to all enrolled students! {resolved} pending requests resolved and notified.",
    )
    return redirect(next_url)


@teacher_required
def teacher_download_history_view(request, item_id):
    """
    Display per-file download history from DownloadLog (who, when, IP).
    """
    item = get_object_or_404(
        MaterialItem.objects.select_related("material", "material__course"),
        pk=item_id,
    )
    logs = (
        DownloadLog.objects.filter(material_item=item)
        .select_related("student")
        .order_by("-downloaded_at")[:100]
    )

    context = {
        "item": item,
        "course": item.material.course,
        "logs": logs,
    }
    return render(request, "dashboard/teacher_download_history.html", context)
