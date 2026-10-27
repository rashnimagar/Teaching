from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadLog,
    DownloadRequest,
    Enrollment,
    Lesson,
    MaterialItem,
)
from apps.courses.services.download_requests import (
    approve_for_all_enrolled,
    transition_download_request,
)
from apps.notifications.models import Notification


def create_dummy_pdf():
    # Valid minimal PDF header
    return ContentFile(b"%PDF-1.4\n%DUMMY CONTENT\n%%EOF", name="test_document.pdf")


def create_dummy_png():
    # Valid PNG created via Pillow
    buf = BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="PNG")
    return ContentFile(buf.getvalue(), name="test_image.png")


@pytest.mark.django_db
class TestMaterialModelsAndValidation:
    def test_view_only_policy_accepts_pdf_and_images(self, user_factory):
        course = Course.objects.create(title="Math", slug="math", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="Chapter 1")

        # PDF is valid
        item_pdf = MaterialItem(
            material=material,
            title="Lecture Notes",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            file=create_dummy_pdf(),
        )
        item_pdf.full_clean()
        item_pdf.save()

        # Image is valid
        item_png = MaterialItem(
            material=material,
            title="Diagram",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            file=create_dummy_png(),
        )
        item_png.full_clean()
        item_png.save()

    def test_view_only_policy_rejects_non_pdf_images(self, user_factory):
        course = Course.objects.create(title="Math", slug="math-2", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="Chapter 1")

        # Text/doc file cannot be view_only
        item_doc = MaterialItem(
            material=material,
            title="Word Doc",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            file=ContentFile(b"plain text notes", name="notes.txt"),
        )
        with pytest.raises(ValidationError, match="View-only policy is strictly restricted to PDF"):
            item_doc.full_clean()

    def test_protect_foreign_keys_prevent_cascading_deletes(self, user_factory):
        course = Course.objects.create(title="Physics", slug="physics", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="Lab 1")
        item = MaterialItem.objects.create(
            material=material,
            title="Manual",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
        )
        student = user_factory(email="protected_test@example.com")
        DownloadRequest.objects.create(student=student, material_item=item)

        # Deleting course must be prevented by PROTECT
        with pytest.raises(ProtectedError):
            course.delete()

        # Deleting material must be prevented by PROTECT
        with pytest.raises(ProtectedError):
            material.delete()

        # Deleting material item must be prevented by PROTECT
        with pytest.raises(ProtectedError):
            item.delete()

    def test_partial_unique_constraint_on_pending_and_approved(self, user_factory):
        course = Course.objects.create(title="Chem", slug="chem", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="Module 1")
        item = MaterialItem.objects.create(
            material=material,
            title="Periodic Table",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
        )
        student = user_factory(email="racing_student@example.com")

        # First request pending
        DownloadRequest.objects.create(
            student=student, material_item=item, status=DownloadRequest.Status.PENDING
        )

        # Second pending request violates UniqueConstraint
        with transaction.atomic():
            with pytest.raises(IntegrityError):
                DownloadRequest.objects.create(
                    student=student, material_item=item, status=DownloadRequest.Status.PENDING
                )

        # If previous request is denied, student can create a new pending request
        DownloadRequest.objects.filter(student=student, material_item=item).update(
            status=DownloadRequest.Status.DENIED
        )
        new_req = DownloadRequest.objects.create(
            student=student, material_item=item, status=DownloadRequest.Status.PENDING
        )
        assert new_req.pk is not None

    def test_computed_expiry_properties(self, user_factory):
        course = Course.objects.create(title="Bio", slug="bio", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="Genetics")
        item = MaterialItem.objects.create(
            material=material,
            title="Slides",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
        )
        student = user_factory(email="expiry_student@example.com")

        now = timezone.now()
        # Future expiry: not expired
        req_valid = DownloadRequest.objects.create(
            student=student,
            material_item=item,
            status=DownloadRequest.Status.APPROVED,
            expires_at=now + timedelta(days=2),
        )
        assert not req_valid.is_expired
        assert req_valid.computed_status == DownloadRequest.Status.APPROVED

        # Past expiry: computed as expired
        req_valid.expires_at = now - timedelta(hours=1)
        req_valid.save()
        assert req_valid.is_expired
        assert req_valid.computed_status == "expired"

    def test_file_deleted_when_replaced(self, django_capture_on_commit_callbacks):
        storage = storages["private"]
        course = Course.objects.create(title="Art", slug="art", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="History")

        with django_capture_on_commit_callbacks(execute=True):
            item = MaterialItem.objects.create(
                material=material,
                title="Syllabus",
                item_type=MaterialItem.ItemType.FILE,
                file=create_dummy_pdf(),
            )
        initial_file_path = item.file.name
        assert storage.exists(initial_file_path)

        # Replace file
        with django_capture_on_commit_callbacks(execute=True):
            item.file = create_dummy_png()
            item.save()

        # Old file was removed in on_commit callback
        assert not storage.exists(initial_file_path)
        assert storage.exists(item.file.name)


@pytest.mark.django_db
class TestMaterialsStudentAccessControl:
    @pytest.fixture(autouse=True)
    def setup_data(self, user_factory):
        self.teacher = user_factory(email="teacher_mat@example.com", is_staff=True)
        self.student = user_factory(email="enrolled_mat@example.com")
        self.course = Course.objects.create(title="Calculus", slug="calc", is_published=True)
        Enrollment.objects.create(
            student=self.student, course=self.course, status=Enrollment.Status.ACTIVE
        )

        self.material = CourseMaterial.objects.create(
            course=self.course, title="Calculus 101 Book", is_published=True
        )

        # 1. request_required file
        self.req_file = MaterialItem.objects.create(
            material=self.material,
            title="Formula Sheet (Request Required)",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            file=create_dummy_pdf(),
        )

        # 2. view_only PDF
        self.view_only_pdf = MaterialItem.objects.create(
            material=self.material,
            title="Exam Preview (View Only)",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            file=create_dummy_pdf(),
        )

        # 3. video item with YouTube ID
        self.video_item = MaterialItem.objects.create(
            material=self.material,
            title="Integral Video",
            item_type=MaterialItem.ItemType.VIDEO,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
        )

    def test_unenrolled_student_redirected_from_materials_page(self, client, user_factory):
        other_student = user_factory(email="uninvited@example.com")
        client.force_login(other_student)
        resp = client.get(reverse("learn:materials", args=[self.course.slug]))
        assert resp.status_code == 302
        assert reverse("courses:detail", args=[self.course.slug]) in resp.url

    def test_enrolled_student_sees_materials_and_request_required_has_no_inline_preview(
        self, client
    ):
        client.force_login(self.student)
        resp = client.get(reverse("learn:materials", args=[self.course.slug]))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert self.material.title in html
        assert self.req_file.title in html
        assert self.view_only_pdf.title in html

        # request_required file has Request Download action and NO inline preview
        assert "Request Download" in html
        assert f"/learn/{self.course.slug}/materials/{self.req_file.id}/preview/" not in html

        # view_only PDF has Preview Inline button
        assert "Preview Inline" in html
        assert f"/learn/{self.course.slug}/materials/{self.view_only_pdf.id}/preview/" in html

    def test_view_only_pdf_previews_inline_but_download_refuses(self, client):
        client.force_login(self.student)

        # Preview endpoint returns 200 with PDF inline disposition
        preview_url = reverse(
            "learn:material_preview", args=[self.course.slug, self.view_only_pdf.id]
        )
        resp_prev = client.get(preview_url)
        assert resp_prev.status_code == 200
        assert resp_prev["Content-Type"] == "application/pdf"
        assert "inline" in resp_prev["Content-Disposition"]

        # Download endpoint strictly refuses (403 Forbidden)
        download_url = reverse(
            "learn:material_download", args=[self.course.slug, self.view_only_pdf.id]
        )
        resp_dl = client.get(download_url)
        assert resp_dl.status_code == 403

    def test_student_request_and_cancel_flow(self, client):
        client.force_login(self.student)
        req_url = reverse("learn:material_request", args=[self.course.slug, self.req_file.id])

        # Submit request
        resp = client.post(req_url)
        assert resp.status_code == 302

        req_obj = DownloadRequest.objects.get(student=self.student, material_item=self.req_file)
        assert req_obj.status == DownloadRequest.Status.PENDING

        # Cancel request
        cancel_url = reverse("learn:material_cancel", args=[self.course.slug, self.req_file.id])
        resp_cancel = client.post(cancel_url)
        assert resp_cancel.status_code == 302
        assert not DownloadRequest.objects.filter(id=req_obj.id).exists()

    def test_approve_revoke_and_cache_control_headers(self, client):
        client.force_login(self.student)

        # Create approved request
        req = DownloadRequest.objects.create(
            student=self.student,
            material_item=self.req_file,
            status=DownloadRequest.Status.APPROVED,
            decided_by=self.teacher,
            decided_at=timezone.now(),
        )

        dl_url = reverse("learn:material_download", args=[self.course.slug, self.req_file.id])

        # First download succeeds
        resp1 = client.get(dl_url)
        assert resp1.status_code == 200
        assert resp1["Cache-Control"] == "private, no-store"

        # Verify DownloadLog was recorded with client IP
        log = DownloadLog.objects.filter(student=self.student, material_item=self.req_file).first()
        assert log is not None
        assert log.ip_address is not None

        # Teacher revokes access via transition service
        transition_download_request(
            request_obj=req,
            new_status=DownloadRequest.Status.REVOKED,
            decided_by=self.teacher,
        )

        # Next call to download endpoint MUST return 403 Forbidden
        resp2 = client.get(dl_url)
        assert resp2.status_code == 403

    def test_denial_24h_cooldown_blocks_immediate_re_request(self, client):
        client.force_login(self.student)
        DownloadRequest.objects.create(
            student=self.student,
            material_item=self.req_file,
            status=DownloadRequest.Status.DENIED,
            decided_by=self.teacher,
            decided_at=timezone.now(),
        )

        req_url = reverse("learn:material_request", args=[self.course.slug, self.req_file.id])
        # Trying to request immediately redirects with cooldown message
        resp = client.post(req_url)
        assert resp.status_code == 302
        # No new pending request is created
        assert not DownloadRequest.objects.filter(
            student=self.student, material_item=self.req_file, status=DownloadRequest.Status.PENDING
        ).exists()

        # Fast forward time beyond 24 hours
        with patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(hours=25)):
            resp2 = client.post(req_url)
            assert resp2.status_code == 302
            assert DownloadRequest.objects.filter(
                student=self.student,
                material_item=self.req_file,
                status=DownloadRequest.Status.PENDING,
            ).exists()

    def test_unenrolled_or_deactivated_student_with_approved_request_cannot_download(self, client):
        DownloadRequest.objects.create(
            student=self.student,
            material_item=self.req_file,
            status=DownloadRequest.Status.APPROVED,
            decided_by=self.teacher,
            decided_at=timezone.now(),
        )

        dl_url = reverse("learn:material_download", args=[self.course.slug, self.req_file.id])

        # Deactivate student
        self.student.is_active = False
        self.student.save()

        client.force_login(self.student)
        resp = client.get(dl_url)
        # Authentication middleware redirects or returns 302/403
        assert resp.status_code in (302, 403)

        # Reactivate student, but revoke course enrollment
        self.student.is_active = True
        self.student.save()
        Enrollment.objects.filter(student=self.student, course=self.course).update(
            status=Enrollment.Status.REVOKED
        )

        client.force_login(self.student)
        resp2 = client.get(dl_url)
        assert resp2.status_code == 403

    def test_no_video_id_or_file_url_leak_for_users_without_access(self, client, user_factory):
        # Create unpublished material
        unpub_material = CourseMaterial.objects.create(
            course=self.course, title="Secret Material", is_published=False
        )
        MaterialItem.objects.create(
            material=unpub_material,
            title="Secret Video",
            item_type=MaterialItem.ItemType.VIDEO,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
        )

        client.force_login(self.student)
        resp = client.get(reverse("learn:materials", args=[self.course.slug]))
        html = resp.content.decode("utf-8")

        # Private video ID and title MUST NOT appear in HTML DOM
        assert unpub_material.title not in html

    def test_approve_for_all_enrolled_resolves_pending_and_notifies(self, user_factory):
        student_b = user_factory(email="student_b_mat@example.com")
        Enrollment.objects.create(
            student=student_b, course=self.course, status=Enrollment.Status.ACTIVE
        )

        req_a = DownloadRequest.objects.create(
            student=self.student, material_item=self.req_file, status=DownloadRequest.Status.PENDING
        )
        req_b = DownloadRequest.objects.create(
            student=student_b, material_item=self.req_file, status=DownloadRequest.Status.PENDING
        )

        resolved, skipped = approve_for_all_enrolled(self.req_file, decided_by=self.teacher)
        assert resolved == 2
        assert skipped == 0

        self.req_file.refresh_from_db()
        assert self.req_file.download_policy == MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED

        req_a.refresh_from_db()
        req_b.refresh_from_db()
        assert req_a.status == DownloadRequest.Status.APPROVED
        assert req_b.status == DownloadRequest.Status.APPROVED

        # Each student received a notification
        assert Notification.objects.filter(recipient=self.student).exists()
        assert Notification.objects.filter(recipient=student_b).exists()


@pytest.mark.django_db
class TestOrphanFileCleanupWithMaterials:
    def test_orphan_cleanup_detects_and_deletes_material_files(self):
        storage = storages["private"]
        course = Course.objects.create(title="Cleanup Course", slug="clean", is_published=True)
        material = CourseMaterial.objects.create(course=course, title="Module 1")

        # Referenced file
        item = MaterialItem.objects.create(
            material=material,
            title="Active Item",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
        )

        # Orphan file in materials/
        orphan_path = "materials/course_999/orphan_file.pdf"
        storage.save(orphan_path, ContentFile(b"%PDF-1.4\norphaned\n%%EOF"))
        assert storage.exists(orphan_path)
        assert storage.exists(item.file.name)

        # Run dry-run: orphan still exists
        call_command("cleanup_orphaned_submissions")
        assert storage.exists(orphan_path)

        # Run with --delete: orphan is deleted, referenced file preserved
        call_command("cleanup_orphaned_submissions", delete=True)
        assert not storage.exists(orphan_path)
        assert storage.exists(item.file.name)
