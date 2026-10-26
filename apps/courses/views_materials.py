import os
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.utils import get_client_ip
from apps.courses.models import Course, CourseMaterial, DownloadLog, DownloadRequest, MaterialItem
from apps.courses.permissions import check_material_access
from apps.courses.services.video import build_safe_video_embed_url


def get_decorated_course_materials(course, user, lesson=None):
    """
    Fetches and decorates course materials and items with real-time access states,
    download policies, cooldown calculations, and video embed previews.
    Executes in bounded O(1) queries using prefetching.
    """
    is_staff = user.is_authenticated and (user.is_staff or getattr(user, "is_teacher", False))

    from django.db.models import Prefetch

    items_qs = MaterialItem.objects.all().order_by("order", "id")
    if not is_staff:
        items_qs = items_qs.filter(is_published=True)

    materials_qs = (
        CourseMaterial.objects.filter(course=course)
        .prefetch_related(Prefetch("items", queryset=items_qs))
        .order_by("order", "id")
    )
    if lesson is not None:
        materials_qs = materials_qs.filter(lesson=lesson)

    if not is_staff:
        materials_qs = materials_qs.filter(is_published=True, is_archived=False)

    materials = list(materials_qs)
    all_item_ids = [item.id for m in materials for item in m.items.all()]

    user_requests_by_item = {}
    if all_item_ids and user.is_authenticated:
        reqs = DownloadRequest.objects.filter(
            student=user,
            material_item_id__in=all_item_ids,
        ).order_by("requested_at")
        for req in reqs:
            user_requests_by_item[req.material_item_id] = req

    now = timezone.now()

    for m in materials:
        for item in m.items.all():
            item.state = "default"
            item.can_download = False
            item.can_preview = False
            item.can_request = False
            item.is_pending = False
            item.is_denied = False
            item.is_cooldown = False
            item.is_expired = False
            item.is_revoked = False
            item.cooldown_until = None
            item.embed_url = None
            item.active_request = user_requests_by_item.get(item.id)

            if item.item_type == MaterialItem.ItemType.VIDEO:
                item.embed_url = build_safe_video_embed_url(
                    item.video_provider, item.video_id, item.video_hash
                )

            elif item.item_type == MaterialItem.ItemType.LINK:
                item.can_open_link = bool(item.external_url)

            elif item.item_type == MaterialItem.ItemType.FILE:
                if is_staff:
                    item.can_download = True
                    item.can_preview = item.is_pdf or item.is_image
                    item.state = "staff_bypass"
                elif item.download_policy == MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED:
                    item.can_download = True
                    item.can_preview = item.is_pdf or item.is_image
                    item.state = "open_to_enrolled"
                elif item.download_policy == MaterialItem.DownloadPolicy.VIEW_ONLY:
                    item.can_download = False
                    item.can_preview = item.is_pdf or item.is_image
                    item.state = "view_only"
                elif item.download_policy == MaterialItem.DownloadPolicy.REQUEST_REQUIRED:
                    req = item.active_request
                    if req is None:
                        item.can_request = True
                        item.state = "can_request"
                    elif req.status == DownloadRequest.Status.PENDING:
                        item.is_pending = True
                        item.state = "pending"
                    elif req.status == DownloadRequest.Status.APPROVED:
                        if req.is_expired:
                            item.is_expired = True
                            item.can_request = True
                            item.state = "expired"
                        else:
                            item.can_download = True
                            item.state = "approved"
                    elif req.status == DownloadRequest.Status.DENIED:
                        item.is_denied = True
                        item.teacher_note = req.teacher_note
                        if req.decided_at:
                            cooldown_end = req.decided_at + timedelta(hours=24)
                            if now < cooldown_end:
                                item.is_cooldown = True
                                item.cooldown_until = cooldown_end
                                item.state = "denied_cooldown"
                            else:
                                item.can_request = True
                                item.state = "can_request"
                        else:
                            item.can_request = True
                            item.state = "can_request"
                    elif req.status == DownloadRequest.Status.REVOKED:
                        item.is_revoked = True
                        item.can_request = True
                        item.state = "revoked"

    return materials


@login_required
def course_materials_view(request, course_slug: str):
    """
    Renders the dedicated Materials page for an enrolled course.
    Executes in bounded O(1) queries using prefetching for materials, items,
    and the student's personal download requests.
    """
    course = get_object_or_404(Course, slug=course_slug)
    is_allowed, response = check_material_access(request, course)
    if not is_allowed:
        return response

    is_staff = request.user.is_staff or getattr(request.user, "is_teacher", False)
    materials = get_decorated_course_materials(course, request.user)

    context = {
        "course": course,
        "materials": materials,
        "has_materials": bool(materials),
        "is_staff": is_staff,
    }
    return render(request, "courses/materials_list.html", context)


@login_required
@require_POST
@ratelimit(key="user", rate="15/m", block=True)
def material_request_download_view(request, course_slug: str, item_id: int):
    """
    Submits a download access request for a MaterialItem with request_required policy.
    Enforces 24-hour denial cooldown and handles race conditions via partial UniqueConstraint.
    """
    course = get_object_or_404(Course, slug=course_slug)
    is_allowed, response = check_material_access(request, course, is_api=True)
    if not is_allowed:
        return response

    item = get_object_or_404(
        MaterialItem,
        id=item_id,
        material__course=course,
        item_type=MaterialItem.ItemType.FILE,
    )

    if not (request.user.is_staff or getattr(request.user, "is_teacher", False)) and not item.is_published:
        raise Http404(_("Material item not found."))

    if item.download_policy != MaterialItem.DownloadPolicy.REQUEST_REQUIRED:
        messages.info(request, "This file does not require an access request.")
        return redirect("learn:materials", course_slug=course.slug)

    # Check 24-hour denial cooldown from the latest denied request
    latest_denied = (
        DownloadRequest.objects.filter(
            student=request.user,
            material_item=item,
            status=DownloadRequest.Status.DENIED,
        )
        .order_by("-decided_at")
        .first()
    )
    if latest_denied and latest_denied.decided_at:
        cooldown_end = latest_denied.decided_at + timedelta(hours=24)
        if timezone.now() < cooldown_end:
            messages.error(
                request,
                f"You cannot submit a new request until the 24-hour cooldown ends at {cooldown_end.strftime('%Y-%m-%d %H:%M')} NPT.",
            )
            return redirect("learn:materials", course_slug=course.slug)

    # Create pending request or handle racing requests gracefully
    try:
        DownloadRequest.objects.create(
            student=request.user,
            material_item=item,
            status=DownloadRequest.Status.PENDING,
            requested_at=timezone.now(),
        )
        messages.success(
            request,
            f"Download request for '{item.title}' submitted. You will be notified once reviewed.",
        )
    except IntegrityError:
        # A pending or approved request row already exists for this student & item
        existing = DownloadRequest.objects.filter(
            student=request.user,
            material_item=item,
            status__in=[DownloadRequest.Status.PENDING, DownloadRequest.Status.APPROVED],
        ).first()
        if existing and existing.status == DownloadRequest.Status.APPROVED:
            messages.info(request, "You already have active download permission for this file.")
        else:
            messages.info(request, "Your download request is already pending review.")

    return redirect("learn:materials", course_slug=course.slug)


@login_required
@require_POST
def material_cancel_request_view(request, course_slug: str, item_id: int):
    """
    Allows a student to cancel their own pending download request.
    """
    course = get_object_or_404(Course, slug=course_slug)
    item = get_object_or_404(MaterialItem, id=item_id, material__course=course)

    deleted_count, _ = DownloadRequest.objects.filter(
        student=request.user,
        material_item=item,
        status=DownloadRequest.Status.PENDING,
    ).delete()

    if deleted_count > 0:
        messages.success(request, f"Cancelled pending request for '{item.title}'.")
    else:
        messages.info(request, "No pending request found to cancel.")

    return redirect("learn:materials", course_slug=course.slug)


@login_required
@ratelimit(key="user", rate="60/m", block=True)
def material_download_view(request, course_slug: str, item_id: int):
    """
    Secure file download endpoint for material items.
    Strictly re-checks on every request:
    - Active enrollment
    - Course published/archived rules
    - Material published and unarchived
    - File policy (view_only strictly refused)
    - Valid, unexpired approved request (if request_required)
    - Staff bypass
    - Cache-Control: private, no-store
    - Audit logging into DownloadLog
    """
    course = get_object_or_404(Course, slug=course_slug)
    item = get_object_or_404(
        MaterialItem,
        id=item_id,
        material__course=course,
        item_type=MaterialItem.ItemType.FILE,
    )

    is_allowed, response = check_material_access(request, course, material=item.material, is_api=True)
    if not is_allowed:
        return response

    is_staff = request.user.is_staff or getattr(request.user, "is_teacher", False)

    # 1. Staff bypass grants immediate download
    if not is_staff:
        if not item.is_published:
            raise Http404(_("Material item not found."))

        # 2. View-only policy strictly forbids downloads
        if item.download_policy == MaterialItem.DownloadPolicy.VIEW_ONLY:
            raise PermissionDenied(_("This file is marked as view-only and cannot be downloaded."))

        # 3. Request-required policy checks for valid approved, unexpired request
        if item.download_policy == MaterialItem.DownloadPolicy.REQUEST_REQUIRED:
            approved_req = DownloadRequest.objects.filter(
                student=request.user,
                material_item=item,
                status=DownloadRequest.Status.APPROVED,
            ).first()

            if not approved_req:
                raise PermissionDenied(_("You do not have an approved request to download this file."))

            if approved_req.is_expired:
                raise PermissionDenied(_("Your download permission for this file has expired."))

    if not item.file or not item.file.name:
        raise Http404(_("File not found on storage."))

    # Audit download in DownloadLog
    client_ip = get_client_ip(None, request)
    DownloadLog.objects.create(
        student=request.user,
        material_item=item,
        downloaded_at=timezone.now(),
        ip_address=client_ip,
    )

    # Serve file with private, no-store headers and safe filename
    filename = item.original_filename or os.path.basename(item.file.name)
    response = FileResponse(
        item.file.open("rb"),
        as_attachment=True,
        filename=filename,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@ratelimit(key="user", rate="60/m", block=True)
def material_preview_view(request, course_slug: str, item_id: int):
    """
    Inline browser preview endpoint strictly for PDF documents and image files.
    Allowed for view_only policy (and open_to_enrolled or staff).
    Strictly refused for request_required policy (which has no inline preview).
    """
    course = get_object_or_404(Course, slug=course_slug)
    item = get_object_or_404(
        MaterialItem,
        id=item_id,
        material__course=course,
        item_type=MaterialItem.ItemType.FILE,
    )

    is_allowed, response = check_material_access(request, course, material=item.material, is_api=True)
    if not is_allowed:
        return response

    is_staff = request.user.is_staff or getattr(request.user, "is_teacher", False)

    if not is_staff and not item.is_published:
        raise Http404(_("Material item not found."))

    # request_required files have NO inline view (Requirement 13)
    if not is_staff and item.download_policy == MaterialItem.DownloadPolicy.REQUEST_REQUIRED:
        raise PermissionDenied(_("Files with request-required policy do not permit inline viewing."))

    if not (item.is_pdf or item.is_image):
        raise PermissionDenied(_("Inline preview is only supported for PDF documents and images."))

    if not item.file or not item.file.name:
        raise Http404(_("File not found on storage."))

    content_type = "application/pdf" if item.is_pdf else f"image/{item.file_extension}"
    response = FileResponse(
        item.file.open("rb"),
        as_attachment=False,
        content_type=content_type,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
