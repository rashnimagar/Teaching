from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadLog,
    DownloadRequest,
    Enrollment,
    MaterialItem,
)
from apps.courses.services.download_requests import transition_download_request
from apps.notifications.models import Notification


def create_dummy_pdf():
    return ContentFile(b"%PDF-1.4\n%DUMMY\n%%EOF", name="test_sheet.pdf")


@pytest.mark.django_db
class TestTeacherPermissionsQueue:
    @pytest.fixture(autouse=True)
    def setup_data(self, user_factory):
        self.teacher = user_factory(
            email="lead_teacher@example.com",
            role=User.Role.TEACHER,
            is_staff=True,
        )
        self.student = user_factory(
            email="queue_student@example.com",
            role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(title="Statistics", slug="stats", is_published=True)
        Enrollment.objects.create(
            student=self.student, course=self.course, status=Enrollment.Status.ACTIVE
        )
        self.material = CourseMaterial.objects.create(
            course=self.course, title="Week 1 Materials", is_published=True
        )
        self.item = MaterialItem.objects.create(
            material=self.material,
            title="Formula Sheet",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            file=create_dummy_pdf(),
        )

    def test_non_teacher_gets_403_on_permissions_queue(self, client):
        client.force_login(self.student)
        resp = client.get(reverse("dashboard:teacher_permissions"))
        assert resp.status_code == 403

    def test_teacher_can_view_permissions_queue_and_filter(self, client):
        DownloadRequest.objects.create(
            student=self.student,
            material_item=self.item,
            status=DownloadRequest.Status.PENDING,
        )

        client.force_login(self.teacher)
        resp = client.get(reverse("dashboard:teacher_permissions"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Download Permissions Queue" in html
        assert self.student.email in html
        assert self.item.title in html
        assert "Pending" in html

        # Filter by status=approved (should be empty)
        resp_approved = client.get(f"{reverse('dashboard:teacher_permissions')}?status=approved")
        assert resp_approved.status_code == 200
        assert "No download requests found" in resp_approved.content.decode("utf-8")

    def test_teacher_single_approve_creates_one_notification_and_sets_expiry(self, client):
        req = DownloadRequest.objects.create(
            student=self.student,
            material_item=self.item,
            status=DownloadRequest.Status.PENDING,
        )

        client.force_login(self.teacher)
        url = reverse("dashboard:teacher_permission_action", args=[req.id])
        resp = client.post(url, {"action": "approve", "expiry_days": "7"})
        assert resp.status_code == 302

        req.refresh_from_db()
        assert req.status == DownloadRequest.Status.APPROVED
        assert req.decided_by == self.teacher
        assert req.expires_at is not None
        assert not req.is_expired

        # Exactly 1 notification created
        notifs = Notification.objects.filter(recipient=self.student)
        assert notifs.count() == 1
        assert "Approved" in notifs.first().title

    def test_teacher_single_deny_with_note(self, client):
        req = DownloadRequest.objects.create(
            student=self.student,
            material_item=self.item,
            status=DownloadRequest.Status.PENDING,
        )

        client.force_login(self.teacher)
        url = reverse("dashboard:teacher_permission_action", args=[req.id])
        resp = client.post(url, {"action": "deny", "teacher_note": "Please submit homework first."})
        assert resp.status_code == 302

        req.refresh_from_db()
        assert req.status == DownloadRequest.Status.DENIED
        assert req.teacher_note == "Please submit homework first."

        notif = Notification.objects.filter(recipient=self.student).first()
        assert "Denied" in notif.title
        assert "Please submit homework first." in notif.body

    def test_teacher_revoke_and_restore(self, client):
        req = DownloadRequest.objects.create(
            student=self.student,
            material_item=self.item,
            status=DownloadRequest.Status.APPROVED,
            decided_by=self.teacher,
            decided_at=timezone.now(),
        )

        client.force_login(self.teacher)
        action_url = reverse("dashboard:teacher_permission_action", args=[req.id])

        # Revoke
        resp_revoke = client.post(action_url, {"action": "revoke"})
        assert resp_revoke.status_code == 302
        req.refresh_from_db()
        assert req.status == DownloadRequest.Status.REVOKED

        # Restore
        resp_restore = client.post(action_url, {"action": "restore"})
        assert resp_restore.status_code == 302
        req.refresh_from_db()
        assert req.status == DownloadRequest.Status.APPROVED

    def test_idempotent_approval_double_submit(self):
        req = DownloadRequest.objects.create(
            student=self.student,
            material_item=self.item,
            status=DownloadRequest.Status.PENDING,
        )

        now = timezone.now()
        # First call: succeeds
        _, success1, _ = transition_download_request(
            request_obj=req,
            new_status=DownloadRequest.Status.APPROVED,
            decided_by=self.teacher,
            expires_at=now + timedelta(days=7),
        )
        assert success1

        # Second identical call: idempotent no-op, does NOT error or duplicate notification
        _, success2, msg2 = transition_download_request(
            request_obj=req,
            new_status=DownloadRequest.Status.APPROVED,
            decided_by=self.teacher,
            expires_at=now + timedelta(days=7),
        )
        assert not success2
        assert "already approved" in msg2
        assert Notification.objects.filter(recipient=self.student).count() == 1

    def test_bulk_actions_apply_per_row_and_skip_invalid(self, client, user_factory):
        student2 = user_factory(email="bulk_student2@example.com")
        student3 = user_factory(email="bulk_student3@example.com")

        # req1: Pending -> target for approve
        req1 = DownloadRequest.objects.create(
            student=self.student, material_item=self.item, status=DownloadRequest.Status.PENDING
        )
        # req2: Pending -> target for approve
        req2 = DownloadRequest.objects.create(
            student=student2, material_item=self.item, status=DownloadRequest.Status.PENDING
        )
        # req3: Already Revoked -> invalid transition to DENIED
        req3 = DownloadRequest.objects.create(
            student=student3, material_item=self.item, status=DownloadRequest.Status.REVOKED
        )

        client.force_login(self.teacher)
        bulk_url = reverse("dashboard:teacher_permissions_bulk_action")

        # Bulk Deny on req1, req2, req3
        resp = client.post(
            bulk_url,
            {
                "bulk_action": "deny",
                "selected_ids": [str(req1.id), str(req2.id), str(req3.id)],
                "bulk_teacher_note": "Batch rejection note.",
            },
        )
        assert resp.status_code == 302

        req1.refresh_from_db()
        req2.refresh_from_db()
        req3.refresh_from_db()

        # req1 and req2 became DENIED
        assert req1.status == DownloadRequest.Status.DENIED
        assert req2.status == DownloadRequest.Status.DENIED
        # req3 was skipped because REVOKED -> DENIED is not allowed
        assert req3.status == DownloadRequest.Status.REVOKED

    def test_approve_for_all_enrolled_view(self, client):
        client.force_login(self.teacher)
        url = reverse("dashboard:teacher_approve_for_all", args=[self.item.id])
        resp = client.post(url)
        assert resp.status_code == 302

        self.item.refresh_from_db()
        assert self.item.download_policy == MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED

    def test_teacher_download_history_view(self, client):
        DownloadLog.objects.create(
            student=self.student,
            material_item=self.item,
            ip_address="192.168.1.100",
        )

        client.force_login(self.teacher)
        url = reverse("dashboard:teacher_download_history", args=[self.item.id])
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Download History" in html
        assert self.student.email in html
        assert "192.168.1.100" not in html
        assert self.item.title in html
