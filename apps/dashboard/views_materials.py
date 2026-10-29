import logging

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import teacher_required
from apps.core.ratelimit import track_ratelimit as ratelimit
from apps.courses.models import Course, CourseMaterial, DownloadLog, DownloadRequest, MaterialItem
from apps.courses.services.download_requests import (
    approve_for_all_enrolled,
    switch_policy_away_from_open_to_enrolled,
    switch_policy_to_view_only,
)
from apps.courses.validators_materials import VIEW_ONLY_ALLOWED_EXTENSIONS
from apps.dashboard.forms_teacher import TeacherMaterialForm, TeacherMaterialItemForm

logger = logging.getLogger(__name__)


@teacher_required
@require_http_methods(["GET"])
def teacher_materials_course_picker_view(request):
    """
    Landing picker for managing materials across courses.
    Lists all non-archived courses with materials and item counts.
    """
    courses = (
        Course.objects.filter(is_archived=False)
        .annotate(
            materials_count=Count(
                "materials", filter=Q(materials__is_archived=False), distinct=True
            ),
            items_count=Count(
                "materials__items", filter=Q(materials__is_archived=False), distinct=True
            ),
        )
        .order_by("title")
    )
    return render(
        request,
        "dashboard/materials/course_picker.html",
        {"courses": courses},
    )


@teacher_required
@require_http_methods(["GET"])
def teacher_materials_list_view(request, slug):
    """
    Materials & resources list for a course.
    Prefetches items, computes download counts and pending requests via bounded queries.
    """
    course = get_object_or_404(Course, slug=slug)

    # Subqueries for bounded counts
    pending_req_subquery = Subquery(
        DownloadRequest.objects.filter(
            material_item__material=OuterRef("pk"),
            status=DownloadRequest.Status.PENDING,
        )
        .values("material_item__material")
        .annotate(cnt=Count("pk"))
        .values("cnt")[:1]
    )

    download_logs_subquery = Subquery(
        DownloadLog.objects.filter(material_item__material=OuterRef("pk"))
        .values("material_item__material")
        .annotate(cnt=Count("pk"))
        .values("cnt")[:1]
    )

    materials = (
        CourseMaterial.objects.filter(course=course)
        .select_related("lesson")
        .prefetch_related("items")
        .annotate(
            pending_requests_count=pending_req_subquery,
            total_downloads_count=download_logs_subquery,
        )
        .order_by("order", "id")
    )

    total_count = materials.count()
    published_count = materials.filter(is_published=True).count()
    archived_count = materials.filter(is_archived=True).count()
    total_items = MaterialItem.objects.filter(material__course=course).count()

    context = {
        "course": course,
        "materials": materials,
        "total_count": total_count,
        "published_count": published_count,
        "archived_count": archived_count,
        "total_items": total_items,
    }
    return render(request, "dashboard/materials/material_list.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_material_create_view(request, slug):
    """Create a new CourseMaterial container."""
    course = get_object_or_404(Course, slug=slug)

    if request.method == "POST":
        form = TeacherMaterialForm(request.POST, course=course)
        if form.is_valid():
            material = form.save()
            messages.success(
                request,
                _("Resource container '%(title)s' created.") % {"title": material.title},
            )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)
    else:
        form = TeacherMaterialForm(course=course)

    context = {
        "course": course,
        "material": None,
        "form": form,
        "is_create": True,
    }
    return render(request, "dashboard/materials/material_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_material_edit_view(request, slug, material_id):
    """Edit an existing CourseMaterial container."""
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)

    if request.method == "POST":
        form = TeacherMaterialForm(request.POST, instance=material, course=course)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("Resource container '%(title)s' updated.") % {"title": material.title},
            )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)
    else:
        form = TeacherMaterialForm(instance=material, course=course)

    context = {
        "course": course,
        "material": material,
        "form": form,
        "is_create": False,
    }
    return render(request, "dashboard/materials/material_form.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_material_toggle_publish_view(request, slug, material_id):
    """Toggle published state of a CourseMaterial post."""
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)

    material.is_published = not material.is_published
    material.save(update_fields=["is_published", "updated_at"])

    status_str = _("published") if material.is_published else _("unpublished")
    messages.success(
        request,
        _("Resource container '%(title)s' is now %(status)s.")
        % {"title": material.title, "status": status_str},
    )
    return redirect("dashboard:teacher_course_materials", slug=course.slug)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_material_archive_view(request, slug, material_id):
    """Toggle archived state of a CourseMaterial post."""
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)

    material.is_archived = not material.is_archived
    material.save(update_fields=["is_archived", "updated_at"])

    status_str = _("archived") if material.is_archived else _("unarchived")
    messages.success(
        request,
        _("Resource container '%(title)s' is now %(status)s.")
        % {"title": material.title, "status": status_str},
    )
    return redirect("dashboard:teacher_course_materials", slug=course.slug)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_material_delete_view(request, slug, material_id):
    """
    Hard-delete a CourseMaterial post.
    Allowed only if none of its items have download history (requests or logs).
    When allowed, removes all of its items' stored files after commit.
    """
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)

    # Check for download requests or download logs across any items
    has_requests = DownloadRequest.objects.filter(material_item__material=material).exists()
    has_logs = DownloadLog.objects.filter(material_item__material=material).exists()

    if has_requests or has_logs:
        messages.error(
            request,
            _(
                "Cannot delete '%(title)s' because it has student download requests or access logs. "
                "You can unpublish or archive it instead."
            )
            % {"title": material.title},
        )
        return redirect("dashboard:teacher_course_materials", slug=course.slug)

    with transaction.atomic():
        # Deleting items triggers post_delete cleanup signal to remove physical files on commit
        for item in list(material.items.all()):
            item.delete()
        material_title = material.title
        material.delete()

    messages.success(
        request,
        _("Resource container '%(title)s' and its items have been deleted.")
        % {"title": material_title},
    )
    return redirect("dashboard:teacher_course_materials", slug=course.slug)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_material_item_create_view(request, slug, material_id):
    """Add a new item (file, link, video) inside a CourseMaterial."""
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)

    if request.method == "POST":
        form = TeacherMaterialItemForm(request.POST, request.FILES, material=material)
        if form.is_valid():
            item = form.save()
            messages.success(
                request,
                _("Resource item '%(title)s' added.") % {"title": item.title},
            )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)
    else:
        form = TeacherMaterialItemForm(material=material)

    context = {
        "course": course,
        "material": material,
        "item": None,
        "form": form,
        "is_create": True,
    }
    return render(request, "dashboard/materials/item_form.html", context)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_material_item_edit_view(request, slug, material_id, item_id):
    """
    Edit an existing MaterialItem.
    If a file is replaced, preserves approvals, deletes old file on commit, and shows a notice.
    """
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)
    item = get_object_or_404(MaterialItem, pk=item_id, material=material)

    if request.method == "POST":
        form = TeacherMaterialItemForm(
            request.POST, request.FILES, instance=item, material=material
        )
        if form.is_valid():
            replaced_file = form.is_replacing_file
            item = form.save()
            if replaced_file:
                messages.info(
                    request,
                    _(
                        "File was replaced for '%(title)s'. Existing student download approvals remain active."
                    )
                    % {"title": item.title},
                )
            messages.success(
                request,
                _("Resource item '%(title)s' updated.") % {"title": item.title},
            )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)
    else:
        form = TeacherMaterialItemForm(instance=item, material=material)

    context = {
        "course": course,
        "material": material,
        "item": item,
        "form": form,
        "is_create": False,
    }
    return render(request, "dashboard/materials/item_form.html", context)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_material_item_toggle_publish_view(request, slug, material_id, item_id):
    """Toggle published state of an individual MaterialItem."""
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)
    item = get_object_or_404(MaterialItem, pk=item_id, material=material)

    item.is_published = not item.is_published
    item.save(update_fields=["is_published", "updated_at"])

    status_str = _("published") if item.is_published else _("hidden as draft")
    messages.success(
        request,
        _("Item '%(title)s' is now %(status)s.") % {"title": item.title, "status": status_str},
    )
    return redirect("dashboard:teacher_course_materials", slug=course.slug)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="30/m", block=True)
def teacher_material_item_delete_view(request, slug, material_id, item_id):
    """
    Hard-delete an individual MaterialItem.
    Allowed ONLY when the item has no DownloadRequest or DownloadLog rows;
    items with history can be unpublished instead.
    """
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)
    item = get_object_or_404(MaterialItem, pk=item_id, material=material)

    has_requests = DownloadRequest.objects.filter(material_item=item).exists()
    has_logs = DownloadLog.objects.filter(material_item=item).exists()

    if has_requests or has_logs:
        messages.error(
            request,
            _(
                "Cannot delete item '%(title)s' because it has student download requests or access logs. "
                "You can unpublish it instead."
            )
            % {"title": item.title},
        )
        return redirect("dashboard:teacher_course_materials", slug=course.slug)

    title = item.title
    # post_delete signal cleans up stored physical file on commit
    item.delete()

    messages.success(
        request,
        _("Item '%(title)s' has been deleted.") % {"title": title},
    )
    return redirect("dashboard:teacher_course_materials", slug=course.slug)


@require_http_methods(["POST"])
@teacher_required
@ratelimit(key="user", rate="60/m", block=True)
def teacher_material_item_reorder_view(request, slug, material_id, item_id):
    """
    Reorder items inside a CourseMaterial container using select_for_update() inside transaction.atomic().
    """
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)
    direction = request.POST.get("direction", "up")

    with transaction.atomic():
        items = list(
            MaterialItem.objects.select_for_update()
            .filter(material=material)
            .order_by("order", "id")
        )

        target_idx = None
        for idx, itm in enumerate(items):
            if itm.id == item_id:
                target_idx = idx
                break

        if target_idx is None:
            raise Http404(_("Item does not belong to this resource."))

        if direction == "up" and target_idx > 0:
            swap_idx = target_idx - 1
            items[target_idx], items[swap_idx] = items[swap_idx], items[target_idx]
        elif direction == "down" and target_idx < len(items) - 1:
            swap_idx = target_idx + 1
            items[target_idx], items[swap_idx] = items[swap_idx], items[target_idx]

        for new_order, itm in enumerate(items, start=1):
            if itm.order != new_order:
                itm.order = new_order
                itm.save(update_fields=["order", "updated_at"])

    messages.success(request, _("Item order updated."))
    return redirect("dashboard:teacher_course_materials", slug=course.slug)


@teacher_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", block=True, method=["POST"])
def teacher_material_item_policy_view(request, slug, material_id, item_id):
    """
    Manage download policy transitions for a MaterialItem:
    - Switching to view_only: requires PDF/image, denies pending requests, revokes approved requests.
    - Switching away from open_to_enrolled: shows download count, offers 'keep access' option.
    - Switching to open_to_enrolled: approves all pending and notifies students.
    """
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)
    item = get_object_or_404(MaterialItem, pk=item_id, material=material)

    if item.item_type != MaterialItem.ItemType.FILE:
        messages.error(request, _("Download policies only apply to file items."))
        return redirect("dashboard:teacher_course_materials", slug=course.slug)

    downloaded_count = (
        DownloadLog.objects.filter(material_item=item).values("student").distinct().count()
    )
    pending_count = DownloadRequest.objects.filter(
        material_item=item, status=DownloadRequest.Status.PENDING
    ).count()
    approved_count = DownloadRequest.objects.filter(
        material_item=item, status=DownloadRequest.Status.APPROVED
    ).count()

    if request.method == "POST":
        target_policy = request.POST.get("target_policy", "").strip()

        if target_policy not in dict(MaterialItem.DownloadPolicy.choices):
            messages.error(request, _("Invalid download policy selected."))
            return redirect("dashboard:teacher_course_materials", slug=course.slug)

        if target_policy == item.download_policy:
            messages.info(request, _("Download policy unchanged."))
            return redirect("dashboard:teacher_course_materials", slug=course.slug)

        # 1. Switching to view_only
        if target_policy == MaterialItem.DownloadPolicy.VIEW_ONLY:
            ext = item.file_extension
            if ext not in VIEW_ONLY_ALLOWED_EXTENSIONS:
                messages.error(
                    request,
                    _(
                        "Cannot switch to View Only: this policy is strictly restricted to PDF documents "
                        "and image files (PNG, JPG). Current file extension is '.%(ext)s'."
                    )
                    % {"ext": ext or "none"},
                )
                return redirect(
                    "dashboard:teacher_material_item_policy",
                    slug=course.slug,
                    material_id=material.id,
                    item_id=item.id,
                )

            denied, revoked = switch_policy_to_view_only(item, decided_by=request.user)
            messages.success(
                request,
                _(
                    "Policy switched to View Only. %(denied)s pending request(s) closed as denied "
                    "and %(revoked)s approved request(s) revoked."
                )
                % {"denied": denied, "revoked": revoked},
            )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)

        # 2. Switching away from open_to_enrolled
        if item.download_policy == MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED:
            keep_access = request.POST.get("keep_access") == "on"
            dl_cnt, pres_cnt = switch_policy_away_from_open_to_enrolled(
                material_item=item,
                new_policy=target_policy,
                keep_access_for_existing=keep_access,
                decided_by=request.user,
            )
            if keep_access:
                messages.success(
                    request,
                    _(
                        "Policy updated to %(policy)s. %(pres)s of %(dl)s students who downloaded "
                        "the file have their approved access preserved."
                    )
                    % {
                        "policy": dict(MaterialItem.DownloadPolicy.choices).get(target_policy),
                        "pres": pres_cnt,
                        "dl": dl_cnt,
                    },
                )
            else:
                messages.success(
                    request,
                    _(
                        "Policy updated to %(policy)s. Access was not preserved for prior downloaders."
                    )
                    % {"policy": dict(MaterialItem.DownloadPolicy.choices).get(target_policy)},
                )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)

        # 3. Switching to open_to_enrolled
        if target_policy == MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED:
            resolved, _skipped = approve_for_all_enrolled(item, decided_by=request.user)
            messages.success(
                request,
                _(
                    "Item is now open to all enrolled students. %(resolved)s pending request(s) approved and notified."
                )
                % {"resolved": resolved},
            )
            return redirect("dashboard:teacher_course_materials", slug=course.slug)

        # 4. Other transitions (e.g. view_only -> request_required)
        item.download_policy = target_policy
        item.save(update_fields=["download_policy", "updated_at"])
        messages.success(
            request,
            _("Download policy updated to %(policy)s.")
            % {"policy": dict(MaterialItem.DownloadPolicy.choices).get(target_policy)},
        )
        return redirect("dashboard:teacher_course_materials", slug=course.slug)

    context = {
        "course": course,
        "material": material,
        "item": item,
        "downloaded_count": downloaded_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "policies": MaterialItem.DownloadPolicy.choices,
    }
    return render(request, "dashboard/materials/item_policy.html", context)


@teacher_required
@require_http_methods(["GET"])
def teacher_material_item_history_view(request, slug, material_id, item_id):
    """
    Display download history for a specific material item.
    Shows student, file name, and Kathmandu timestamp only (NO IP ADDRESS).
    """
    course = get_object_or_404(Course, slug=slug)
    material = get_object_or_404(CourseMaterial, pk=material_id, course=course)
    item = get_object_or_404(MaterialItem, pk=item_id, material=material)

    logs = (
        DownloadLog.objects.filter(material_item=item)
        .select_related("student")
        .order_by("-downloaded_at")[:100]
    )

    context = {
        "course": course,
        "material": material,
        "item": item,
        "logs": logs,
    }
    return render(request, "dashboard/materials/item_history.html", context)
