from datetime import datetime

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.courses.models import DownloadRequest, MaterialItem
from apps.notifications.models import Notification
from apps.notifications.services import create_notification

ALLOWED_TRANSITIONS = {
    (DownloadRequest.Status.PENDING, DownloadRequest.Status.APPROVED),
    (DownloadRequest.Status.PENDING, DownloadRequest.Status.DENIED),
    (DownloadRequest.Status.APPROVED, DownloadRequest.Status.REVOKED),
    (DownloadRequest.Status.DENIED, DownloadRequest.Status.APPROVED),  # Reconsideration
    (DownloadRequest.Status.REVOKED, DownloadRequest.Status.APPROVED),  # Restore
}


def transition_download_request(
    request_obj: DownloadRequest,
    new_status: str,
    decided_by,
    teacher_note: str = "",
    expires_at: datetime | None = None,
) -> tuple[DownloadRequest, bool, str]:
    """
    Central, race-safe state transition service for DownloadRequests.
    Used uniformly across the Teacher Dashboard, bulk actions, and Django admin.

    Guarantees:
    - Atomicity & row locking via select_for_update()
    - Idempotency: duplicate approvals with the same expiry date are no-ops
    - Exactly one notification created in the same transaction
    - Re-evaluates state transitions strictly
    """
    with transaction.atomic():
        # Lock and refresh current state
        locked_req = (
            DownloadRequest.objects.select_for_update()
            .select_related("student", "material_item", "material_item__material", "material_item__material__course")
            .get(pk=request_obj.pk)
        )
        current_status = locked_req.status

        # Idempotency check: if already in target state
        if current_status == new_status:
            if new_status == DownloadRequest.Status.APPROVED and locked_req.expires_at == expires_at:
                return locked_req, False, "Request is already approved with identical expiry."
            if new_status == DownloadRequest.Status.DENIED:
                return locked_req, False, "Request is already denied."
            if new_status == DownloadRequest.Status.REVOKED:
                return locked_req, False, "Request is already revoked."

        # Validate transition pair
        transition_pair = (current_status, new_status)
        if transition_pair not in ALLOWED_TRANSITIONS:
            return (
                locked_req,
                False,
                f"Invalid transition from {locked_req.get_status_display()} to {new_status}.",
            )

        now = timezone.now()
        locked_req.status = new_status
        locked_req.decided_by = decided_by
        locked_req.decided_at = now

        item = locked_req.material_item
        course = item.material.course
        materials_url = reverse("learn:materials", kwargs={"course_slug": course.slug})

        if new_status == DownloadRequest.Status.APPROVED:
            locked_req.expires_at = expires_at
            expiry_str = f" Access is valid until {expires_at.strftime('%Y-%m-%d %H:%M')} NPT." if expires_at else ""
            notif_kind = Notification.Kind.DOWNLOAD_APPROVED
            notif_title = f"Download Approved: {item.title}"
            notif_body = (
                f"Your request to download '{item.title}' for the course '{course.title}' has been approved.{expiry_str}"
            )

        elif new_status == DownloadRequest.Status.DENIED:
            locked_req.teacher_note = teacher_note.strip()
            notif_kind = Notification.Kind.DOWNLOAD_DENIED
            notif_title = f"Download Request Denied: {item.title}"
            note_part = f"\nTeacher's Note: {locked_req.teacher_note}" if locked_req.teacher_note else ""
            notif_body = (
                f"Your request to download '{item.title}' for '{course.title}' was not approved.{note_part}\n"
                "You may submit a new request after 24 hours."
            )

        elif new_status == DownloadRequest.Status.REVOKED:
            if teacher_note:
                locked_req.teacher_note = teacher_note.strip()
            notif_kind = Notification.Kind.DOWNLOAD_REVOKED
            notif_title = f"Download Access Revoked: {item.title}"
            note_part = f"\nNote: {locked_req.teacher_note}" if locked_req.teacher_note else ""
            notif_body = (
                f"Download access for '{item.title}' in the course '{course.title}' has been revoked by the instructor.{note_part}"
            )

        else:
            return locked_req, False, f"Unsupported status: {new_status}"

        locked_req.save()

        # Create exactly one notification in the same transaction
        create_notification(
            recipient=locked_req.student,
            kind=notif_kind,
            title=notif_title,
            body=notif_body,
            url=materials_url,
        )

        return locked_req, True, f"Request successfully updated to {new_status}."


def approve_for_all_enrolled(material_item: MaterialItem, decided_by) -> tuple[int, int]:
    """
    Switches a material item's download policy to 'open_to_enrolled' and
    automatically resolves all existing pending requests for that item to approved.
    Notifies each student with a pending request.
    """
    with transaction.atomic():
        locked_item = MaterialItem.objects.select_for_update().get(pk=material_item.pk)
        locked_item.download_policy = MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED
        locked_item.save(update_fields=["download_policy", "updated_at"])

        pending_requests = list(
            DownloadRequest.objects.filter(
                material_item=locked_item,
                status=DownloadRequest.Status.PENDING,
            ).select_for_update()
        )

        resolved_count = 0
        skipped_count = 0

        for req in pending_requests:
            _, success, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.APPROVED,
                decided_by=decided_by,
                expires_at=None,
            )
            if success:
                resolved_count += 1
            else:
                skipped_count += 1

        return resolved_count, skipped_count


def switch_policy_to_view_only(material_item: MaterialItem, decided_by) -> tuple[int, int]:
    """
    Switches a material item's download policy to 'view_only'.
    - Validates that the item is a PDF or image file.
    - Closes all pending requests as DENIED with note 'This file is now view-only'.
    - Revokes all approved requests as REVOKED with note 'This file is now view-only'.
    - Notifies each affected student through transition_download_request.
    - Returns (denied_count, revoked_count).
    """
    if not (material_item.is_pdf or material_item.is_image):
        from django.core.exceptions import ValidationError
        raise ValidationError("View-only policy is strictly restricted to PDF documents and image files (PNG, JPG).")

    with transaction.atomic():
        locked_item = MaterialItem.objects.select_for_update().get(pk=material_item.pk)
        locked_item.download_policy = MaterialItem.DownloadPolicy.VIEW_ONLY
        locked_item.save(update_fields=["download_policy", "updated_at"])

        pending_reqs = list(
            DownloadRequest.objects.filter(
                material_item=locked_item,
                status=DownloadRequest.Status.PENDING,
            ).select_for_update()
        )
        approved_reqs = list(
            DownloadRequest.objects.filter(
                material_item=locked_item,
                status=DownloadRequest.Status.APPROVED,
            ).select_for_update()
        )

        denied_count = 0
        for req in pending_reqs:
            _, success, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.DENIED,
                decided_by=decided_by,
                teacher_note="This file is now view-only",
            )
            if success:
                denied_count += 1

        revoked_count = 0
        for req in approved_reqs:
            _, success, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.REVOKED,
                decided_by=decided_by,
                teacher_note="This file is now view-only",
            )
            if success:
                revoked_count += 1

        return denied_count, revoked_count


def switch_policy_away_from_open_to_enrolled(
    material_item: MaterialItem,
    new_policy: str,
    keep_access_for_existing: bool,
    decided_by,
) -> tuple[int, int]:
    """
    Switches a material item's policy away from 'open_to_enrolled'.
    If keep_access_for_existing is True, finds all students who downloaded the file
    from DownloadLog and ensures they have an active APPROVED DownloadRequest.
    Returns (downloaded_student_count, access_preserved_count).
    """
    from apps.courses.models import DownloadLog

    with transaction.atomic():
        locked_item = MaterialItem.objects.select_for_update().get(pk=material_item.pk)
        locked_item.download_policy = new_policy
        locked_item.save(update_fields=["download_policy", "updated_at"])

        downloaded_student_ids = list(
            DownloadLog.objects.filter(material_item=locked_item)
            .values_list("student_id", flat=True)
            .distinct()
        )
        downloaded_count = len(downloaded_student_ids)
        preserved_count = 0

        if keep_access_for_existing and downloaded_student_ids:
            now = timezone.now()
            for student_id in downloaded_student_ids:
                existing_req = (
                    DownloadRequest.objects.filter(
                        student_id=student_id,
                        material_item=locked_item,
                    )
                    .order_by("-requested_at")
                    .first()
                )
                if existing_req:
                    if existing_req.status == DownloadRequest.Status.APPROVED:
                        preserved_count += 1
                    elif existing_req.status == DownloadRequest.Status.PENDING:
                        _, success, _ = transition_download_request(
                            request_obj=existing_req,
                            new_status=DownloadRequest.Status.APPROVED,
                            decided_by=decided_by,
                            teacher_note="Access preserved after policy change.",
                        )
                        if success:
                            preserved_count += 1
                    elif existing_req.status in (DownloadRequest.Status.DENIED, DownloadRequest.Status.REVOKED):
                        _, success, _ = transition_download_request(
                            request_obj=existing_req,
                            new_status=DownloadRequest.Status.APPROVED,
                            decided_by=decided_by,
                            teacher_note="Access restored after policy change.",
                        )
                        if success:
                            preserved_count += 1
                else:
                    DownloadRequest.objects.create(
                        student_id=student_id,
                        material_item=locked_item,
                        status=DownloadRequest.Status.APPROVED,
                        decided_by=decided_by,
                        decided_at=now,
                        teacher_note="Access granted based on prior downloads.",
                    )
                    preserved_count += 1

        return downloaded_count, preserved_count

