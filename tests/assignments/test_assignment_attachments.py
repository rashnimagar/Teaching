import logging
from datetime import timedelta
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.assignments.models import (
    Assignment,
    AssignmentAttachment,
    AssignmentAttachmentDownload,
    Submission,
)
from apps.courses.models import Course, Enrollment, Lesson
from apps.courses.validators_materials import validate_material_file


def create_dummy_pdf(content: bytes = b"%PDF-1.4\n%DUMMY CONTENT\n%%EOF", name: str = "test.pdf"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def create_dummy_png(name: str = "test.png"):
    buf = BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture
def course_fixture(db):
    return Course.objects.create(
        title="Software Security",
        slug="software-security",
        is_published=True,
    )


@pytest.fixture
def teacher_fixture(db, user_factory):
    return user_factory(
        email="teacher@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )


@pytest.fixture
def student_fixture(db, user_factory):
    return user_factory(
        email="student@example.com",
        role=User.Role.STUDENT,
    )


@pytest.fixture
def active_enrollment(student_fixture, course_fixture):
    return Enrollment.objects.create(
        student=student_fixture,
        course=course_fixture,
        status=Enrollment.Status.ACTIVE,
    )


@pytest.fixture
def published_lesson(course_fixture):
    return Lesson.objects.create(
        course=course_fixture,
        title="Published Lesson 1",
        order=1,
        is_published=True,
    )


@pytest.fixture
def draft_lesson(course_fixture):
    return Lesson.objects.create(
        course=course_fixture,
        title="Draft Lesson 2",
        order=2,
        is_published=False,
    )


@pytest.fixture
def open_assignment(course_fixture, published_lesson):
    return Assignment.objects.create(
        course=course_fixture,
        lesson=published_lesson,
        title="Lab 1: Cryptography",
        instructions="Analyze the cipher and submit your findings.",
        opens_at=timezone.now() - timedelta(days=1),
        due_at=timezone.now() + timedelta(days=5),
        max_score=100,
        is_published=True,
    )


@pytest.fixture
def open_attachment(open_assignment):
    return AssignmentAttachment.objects.create(
        assignment=open_assignment,
        title="Crypto Handout",
        file=create_dummy_pdf(name="crypto_handout.pdf"),
        download_policy=AssignmentAttachment.DownloadPolicy.OPEN_TO_ENROLLED,
        is_published=True,
    )


@pytest.fixture
def view_only_attachment(open_assignment):
    return AssignmentAttachment.objects.create(
        assignment=open_assignment,
        title="Crypto Rubric (View Only)",
        file=create_dummy_pdf(name="crypto_rubric.pdf"),
        download_policy=AssignmentAttachment.DownloadPolicy.VIEW_ONLY,
        is_published=True,
    )


# -----------------------------------------------------------------------------
# 1. Attachment Access Matrix Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestAttachmentAccessMatrix:
    def test_guest_is_redirected_to_login(self, client, course_fixture, open_attachment):
        # Guest download redirect
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        resp = client.get(dl_url)
        assert resp.status_code == 302
        assert reverse("account_login") in resp.url

        # Guest preview redirect
        prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        resp_prev = client.get(prev_url)
        assert resp_prev.status_code == 302
        assert reverse("account_login") in resp_prev.url

    def test_non_enrolled_student_is_denied(
        self, client, user_factory, course_fixture, open_attachment
    ):
        non_enrolled = user_factory(email="stranger@example.com")
        client.force_login(non_enrolled)

        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        resp = client.get(dl_url)
        assert resp.status_code == 403

        prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        resp_prev = client.get(prev_url)
        assert resp_prev.status_code == 403

    def test_pending_and_revoked_enrollment_is_denied(
        self, client, user_factory, course_fixture, open_attachment
    ):
        pending_user = user_factory(email="pending@example.com")
        Enrollment.objects.create(
            student=pending_user, course=course_fixture, status=Enrollment.Status.PENDING
        )
        client.force_login(pending_user)

        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(dl_url).status_code == 403

        revoked_user = user_factory(email="revoked@example.com")
        Enrollment.objects.create(
            student=revoked_user, course=course_fixture, status=Enrollment.Status.REVOKED
        )
        client.force_login(revoked_user)
        assert client.get(dl_url).status_code == 403

    def test_active_student_open_attachment_download_and_preview(
        self, client, student_fixture, active_enrollment, course_fixture, open_attachment
    ):
        client.force_login(student_fixture)

        # Download returns 200 with attachment disposition
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        resp = client.get(dl_url)
        assert resp.status_code == 200
        assert "attachment" in resp["Content-Disposition"]
        assert resp["X-Content-Type-Options"] == "nosniff"
        assert "private" in resp["Cache-Control"]

        # Preview returns 200 inline without sandbox
        prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        resp_prev = client.get(prev_url)
        assert resp_prev.status_code == 200
        assert resp_prev["Content-Type"] == "application/pdf"
        assert resp_prev["X-Frame-Options"] == "SAMEORIGIN"
        assert resp_prev["X-Content-Type-Options"] == "nosniff"
        assert "private" in resp_prev["Cache-Control"]

    def test_view_only_policy_blocks_download_allows_preview(
        self, client, student_fixture, active_enrollment, course_fixture, view_only_attachment
    ):
        client.force_login(student_fixture)

        # Download strictly forbidden (403)
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": view_only_attachment.id},
        )
        resp = client.get(dl_url)
        assert resp.status_code == 403

        # Preview succeeds (200)
        prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": course_fixture.slug, "attachment_id": view_only_attachment.id},
        )
        resp_prev = client.get(prev_url)
        assert resp_prev.status_code == 200

    def test_draft_assignment_hidden_from_students(
        self, client, student_fixture, active_enrollment, course_fixture, open_attachment
    ):
        open_attachment.assignment.is_published = False
        open_attachment.assignment.save()

        client.force_login(student_fixture)
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(dl_url).status_code == 404

        prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(prev_url).status_code == 404

    def test_before_opens_at_hidden_from_students(
        self, client, student_fixture, active_enrollment, course_fixture, open_attachment
    ):
        open_attachment.assignment.opens_at = timezone.now() + timedelta(days=2)
        open_attachment.assignment.due_at = timezone.now() + timedelta(days=7)
        open_attachment.assignment.save()

        client.force_login(student_fixture)
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(dl_url).status_code == 404

    def test_unpublished_attachment_hidden_from_students(
        self, client, student_fixture, active_enrollment, course_fixture, open_attachment
    ):
        open_attachment.is_published = False
        open_attachment.save()

        client.force_login(student_fixture)
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(dl_url).status_code == 404


# -----------------------------------------------------------------------------
# 2. Draft Lesson Isolation Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestDraftLessonIsolation:
    def test_assignment_on_draft_lesson_hidden_from_student_visible_to_teacher(
        self,
        client,
        student_fixture,
        teacher_fixture,
        active_enrollment,
        course_fixture,
        draft_lesson,
    ):
        assign_draft_lesson = Assignment.objects.create(
            course=course_fixture,
            lesson=draft_lesson,
            title="Draft Lesson Lab",
            instructions="Only visible when lesson published.",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=5),
            is_published=True,
        )
        att = AssignmentAttachment.objects.create(
            assignment=assign_draft_lesson,
            title="Draft Lesson Handout",
            file=create_dummy_pdf(name="draft_lesson.pdf"),
            download_policy=AssignmentAttachment.DownloadPolicy.OPEN_TO_ENROLLED,
            is_published=True,
        )

        # 1. Student access -> 404
        client.force_login(student_fixture)

        detail_url = reverse(
            "assignments:detail",
            kwargs={"slug": course_fixture.slug, "assignment_id": assign_draft_lesson.id},
        )
        assert client.get(detail_url).status_code == 404

        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": att.id},
        )
        assert client.get(dl_url).status_code == 404

        prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": course_fixture.slug, "attachment_id": att.id},
        )
        assert client.get(prev_url).status_code == 404

        # Hidden from course assignments list for student
        list_url = reverse("assignments:list", kwargs={"slug": course_fixture.slug})
        resp_list = client.get(list_url)
        assert resp_list.status_code == 200
        assert "Draft Lesson Lab" not in resp_list.content.decode()

        # Hidden from lesson page for student
        lesson_url = reverse(
            "learn:lesson",
            kwargs={"course_slug": course_fixture.slug, "lesson_id": draft_lesson.id},
        )
        # Student cannot even access unpublished lesson page
        assert client.get(lesson_url).status_code == 404

        # 2. Staff / Teacher access -> 200
        client.force_login(teacher_fixture)
        assert client.get(detail_url).status_code == 200
        assert client.get(dl_url).status_code == 200
        assert client.get(prev_url).status_code == 200
        assert "Draft Lesson Lab" in client.get(list_url).content.decode()


# -----------------------------------------------------------------------------
# 3. Cross-Course Isolation Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestCrossCourseIsolation:
    def test_cross_course_attachment_access_returns_404(
        self, client, student_fixture, course_fixture, open_attachment
    ):
        other_course = Course.objects.create(
            title="Other Course",
            slug="other-course",
            is_published=True,
        )
        Enrollment.objects.create(
            student=student_fixture, course=other_course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(student_fixture)

        # Attempting to fetch open_attachment under other_course slug must 404
        bad_dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": other_course.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(bad_dl_url).status_code == 404

        bad_prev_url = reverse(
            "assignments:attachment_preview",
            kwargs={"slug": other_course.slug, "attachment_id": open_attachment.id},
        )
        assert client.get(bad_prev_url).status_code == 404


# -----------------------------------------------------------------------------
# 4. Audit Log Verification Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestAuditLogVerification:
    def test_student_download_audited_with_trusted_ip(
        self, client, student_fixture, active_enrollment, course_fixture, open_attachment
    ):
        client.force_login(student_fixture)
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )

        resp = client.get(dl_url, REMOTE_ADDR="198.51.100.42")
        assert resp.status_code == 200

        record = AssignmentAttachmentDownload.objects.filter(
            attachment=open_attachment, student=student_fixture
        ).first()
        assert record is not None
        assert record.ip_address == "198.51.100.42"

    def test_staff_download_not_audited(
        self, client, teacher_fixture, course_fixture, open_attachment
    ):
        client.force_login(teacher_fixture)
        dl_url = reverse(
            "assignments:attachment_download",
            kwargs={"slug": course_fixture.slug, "attachment_id": open_attachment.id},
        )

        resp = client.get(dl_url, REMOTE_ADDR="198.51.100.99")
        assert resp.status_code == 200

        # No audit records created for staff
        assert not AssignmentAttachmentDownload.objects.filter(attachment=open_attachment).exists()

    def test_teacher_download_history_view_omits_ip_addresses(
        self, client, teacher_fixture, student_fixture, course_fixture, open_attachment
    ):
        AssignmentAttachmentDownload.objects.create(
            attachment=open_attachment,
            student=student_fixture,
            ip_address="203.0.113.195",
        )

        client.force_login(teacher_fixture)
        view_url = reverse(
            "dashboard:teacher_assignment_attachment_downloads",
            kwargs={
                "slug": course_fixture.slug,
                "assignment_id": open_attachment.assignment.id,
                "attachment_id": open_attachment.id,
            },
        )
        resp = client.get(view_url)
        assert resp.status_code == 200
        html = resp.content.decode()

        assert student_fixture.email in html
        assert "203.0.113.195" not in html
        assert "IP address" not in html
        assert "IP Address" not in html


# -----------------------------------------------------------------------------
# 5. Teacher Attachment CRUD & Reorder Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestTeacherAttachmentCRUD:
    def test_add_attachment_increases_order(
        self, client, teacher_fixture, course_fixture, open_assignment
    ):
        client.force_login(teacher_fixture)
        add_url = reverse(
            "dashboard:teacher_assignment_attachment_add",
            kwargs={"slug": course_fixture.slug, "assignment_id": open_assignment.id},
        )

        pdf = create_dummy_pdf(name="new_attachment.pdf")
        resp = client.post(
            add_url,
            {
                "title": "Starter Code Package",
                "download_policy": AssignmentAttachment.DownloadPolicy.OPEN_TO_ENROLLED,
                "file": pdf,
            },
        )
        assert resp.status_code == 302

        att = AssignmentAttachment.objects.get(
            assignment=open_assignment, title="Starter Code Package"
        )
        assert att.order == 1
        assert att.file_size is not None
        assert att.file_size > 0

    def test_edit_attachment_and_replace_file_preserves_download_history(
        self,
        client,
        teacher_fixture,
        student_fixture,
        course_fixture,
        open_attachment,
        django_capture_on_commit_callbacks,
    ):
        storage = storages["private"]
        old_file_path = open_attachment.file.name
        assert storage.exists(old_file_path)

        # Seed download record
        AssignmentAttachmentDownload.objects.create(
            attachment=open_attachment,
            student=student_fixture,
            ip_address="192.0.2.1",
        )

        client.force_login(teacher_fixture)
        edit_url = reverse(
            "dashboard:teacher_assignment_attachment_edit",
            kwargs={
                "slug": course_fixture.slug,
                "assignment_id": open_attachment.assignment.id,
                "attachment_id": open_attachment.id,
            },
        )

        new_pdf = create_dummy_pdf(name="updated_crypto_handout.pdf")
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post(
                edit_url,
                {
                    "title": "Updated Crypto Handout v2",
                    "download_policy": AssignmentAttachment.DownloadPolicy.OPEN_TO_ENROLLED,
                    "file": new_pdf,
                },
            )
        assert resp.status_code == 302

        open_attachment.refresh_from_db()
        assert open_attachment.title == "Updated Crypto Handout v2"
        # Download history preserved
        assert open_attachment.downloads.count() == 1
        # Old file physically deleted after commit, new file exists
        assert not storage.exists(old_file_path)
        assert storage.exists(open_attachment.file.name)

    def test_reorder_attachments_atomically(
        self, client, teacher_fixture, course_fixture, open_assignment
    ):
        att1 = AssignmentAttachment.objects.create(
            assignment=open_assignment,
            title="First",
            order=1,
            file=create_dummy_pdf(name="first.pdf"),
        )
        att2 = AssignmentAttachment.objects.create(
            assignment=open_assignment,
            title="Second",
            order=2,
            file=create_dummy_pdf(name="second.pdf"),
        )

        client.force_login(teacher_fixture)
        reorder_url = reverse(
            "dashboard:teacher_assignment_attachment_reorder",
            kwargs={
                "slug": course_fixture.slug,
                "assignment_id": open_assignment.id,
                "attachment_id": att2.id,
            },
        )
        # Move att2 up
        resp = client.post(reorder_url, {"direction": "up"})
        assert resp.status_code == 302

        att1.refresh_from_db()
        att2.refresh_from_db()
        assert att2.order == 1
        assert att1.order == 2

    def test_toggle_publish(self, client, teacher_fixture, course_fixture, open_attachment):
        assert open_attachment.is_published is True
        client.force_login(teacher_fixture)

        toggle_url = reverse(
            "dashboard:teacher_assignment_attachment_toggle_publish",
            kwargs={
                "slug": course_fixture.slug,
                "assignment_id": open_attachment.assignment.id,
                "attachment_id": open_attachment.id,
            },
        )
        resp = client.post(toggle_url)
        assert resp.status_code == 302

        open_attachment.refresh_from_db()
        assert open_attachment.is_published is False


# -----------------------------------------------------------------------------
# 6. Soft-Hide vs Hard-Delete Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestSoftHideVsHardDelete:
    def test_delete_with_downloads_soft_hides(
        self, client, teacher_fixture, student_fixture, course_fixture, open_attachment
    ):
        # Seed download record
        AssignmentAttachmentDownload.objects.create(
            attachment=open_attachment,
            student=student_fixture,
            ip_address="192.0.2.1",
        )

        client.force_login(teacher_fixture)
        del_url = reverse(
            "dashboard:teacher_assignment_attachment_delete",
            kwargs={
                "slug": course_fixture.slug,
                "assignment_id": open_attachment.assignment.id,
                "attachment_id": open_attachment.id,
            },
        )
        resp = client.post(del_url)
        assert resp.status_code == 302

        # Record still exists but is soft-hidden
        open_attachment.refresh_from_db()
        assert open_attachment.is_published is False
        assert open_attachment.downloads.count() == 1

    def test_delete_without_downloads_hard_deletes_and_cleans_file(
        self,
        client,
        teacher_fixture,
        course_fixture,
        open_attachment,
        django_capture_on_commit_callbacks,
    ):
        storage = storages["private"]
        file_path = open_attachment.file.name
        assert storage.exists(file_path)

        client.force_login(teacher_fixture)
        del_url = reverse(
            "dashboard:teacher_assignment_attachment_delete",
            kwargs={
                "slug": course_fixture.slug,
                "assignment_id": open_attachment.assignment.id,
                "attachment_id": open_attachment.id,
            },
        )
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post(del_url)
        assert resp.status_code == 302

        assert not AssignmentAttachment.objects.filter(id=open_attachment.id).exists()
        assert not storage.exists(file_path)


# -----------------------------------------------------------------------------
# 7. Assignment Deletion Safety Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestAssignmentDeletionSafety:
    def test_delete_blocked_when_student_submissions_exist(
        self,
        client,
        teacher_fixture,
        student_fixture,
        course_fixture,
        open_assignment,
        open_attachment,
    ):
        Submission.objects.create(
            assignment=open_assignment,
            student=student_fixture,
            content_text="Student submission content.",
        )

        client.force_login(teacher_fixture)
        del_url = reverse(
            "dashboard:teacher_course_assignment_delete",
            kwargs={"slug": course_fixture.slug, "assignment_id": open_assignment.id},
        )
        resp = client.post(del_url)
        assert resp.status_code == 302

        # Assignment and attachments remain intact
        assert Assignment.objects.filter(id=open_assignment.id).exists()
        assert AssignmentAttachment.objects.filter(id=open_attachment.id).exists()

    def test_delete_succeeds_without_submissions_and_cleans_attachments(
        self,
        client,
        teacher_fixture,
        course_fixture,
        open_assignment,
        open_attachment,
        django_capture_on_commit_callbacks,
    ):
        storage = storages["private"]
        file_path = open_attachment.file.name
        assert storage.exists(file_path)

        client.force_login(teacher_fixture)
        del_url = reverse(
            "dashboard:teacher_course_assignment_delete",
            kwargs={"slug": course_fixture.slug, "assignment_id": open_assignment.id},
        )
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post(del_url)
        assert resp.status_code == 302

        assert not Assignment.objects.filter(id=open_assignment.id).exists()
        assert not AssignmentAttachment.objects.filter(id=open_attachment.id).exists()
        assert not storage.exists(file_path)


# -----------------------------------------------------------------------------
# 8. Tolerant PDF Validation & Bypass Testing
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestTolerantPDFValidation:
    def test_tolerates_whitespace_and_bom_before_pdf_marker(self):
        # Leading whitespace and BOM before %PDF-
        bom_and_ws = b"\xef\xbb\xbf   \r\n\t%PDF-1.5 test document content"
        f = SimpleUploadedFile("bom_test.pdf", bom_and_ws, content_type="application/pdf")
        validate_material_file(f)

    def test_accepts_uppercase_pdf_spaces_and_nepali_filename(self):
        f = SimpleUploadedFile("UPPERCASE.PDF", b"%PDF-1.4 content", content_type="application/pdf")
        validate_material_file(f)

        f_spaces = SimpleUploadedFile(
            "My Course Handout.pdf", b"%PDF-1.4 content", content_type="application/pdf"
        )
        validate_material_file(f_spaces)

        f_nepali = SimpleUploadedFile(
            "परीक्षण.pdf", b"%PDF-1.4 content", content_type="application/pdf"
        )
        validate_material_file(f_nepali)

    def test_corrupted_pdf_rejected_with_structured_log(self, caplog):
        corrupt = SimpleUploadedFile(
            "bad.pdf", b"NOT A VALID PDF FILE HEADER", content_type="application/pdf"
        )
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValidationError, match="valid PDF"):
                validate_material_file(corrupt)

        assert any("PDF validation failed" in rec.message for rec in caplog.records)

    def test_direct_post_bypassing_client_checks_rejected_by_server(
        self, client, teacher_fixture, course_fixture, open_assignment
    ):
        client.force_login(teacher_fixture)
        add_url = reverse(
            "dashboard:teacher_assignment_attachment_add",
            kwargs={"slug": course_fixture.slug, "assignment_id": open_assignment.id},
        )

        # Upload dangerous executable bypassing client validation
        exe_file = SimpleUploadedFile(
            "malware.exe", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/x-msdownload"
        )
        resp = client.post(
            add_url,
            {
                "title": "Malware Attachment",
                "download_policy": AssignmentAttachment.DownloadPolicy.OPEN_TO_ENROLLED,
                "file": exe_file,
            },
        )
        assert resp.status_code == 302
        assert not AssignmentAttachment.objects.filter(
            assignment=open_assignment, title="Malware Attachment"
        ).exists()


# -----------------------------------------------------------------------------
# 9. Bounded Query Count Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestBoundedQueryCounts:
    def test_lesson_learn_view_bounded_queries(
        self,
        client,
        student_fixture,
        active_enrollment,
        course_fixture,
        published_lesson,
        open_assignment,
        django_assert_max_num_queries,
    ):
        client.force_login(student_fixture)
        lesson_url = reverse(
            "learn:lesson",
            kwargs={"course_slug": course_fixture.slug, "lesson_id": published_lesson.id},
        )

        with django_assert_max_num_queries(20):
            resp = client.get(lesson_url)
            assert resp.status_code == 200

    def test_assignments_list_view_bounded_queries(
        self,
        client,
        student_fixture,
        active_enrollment,
        course_fixture,
        open_assignment,
        django_assert_max_num_queries,
    ):
        client.force_login(student_fixture)
        list_url = reverse("assignments:list", kwargs={"slug": course_fixture.slug})

        with django_assert_max_num_queries(15):
            resp = client.get(list_url)
            assert resp.status_code == 200


# -----------------------------------------------------------------------------
# 10. Populated Template Rendering Tests
# -----------------------------------------------------------------------------
@pytest.mark.django_db
class TestPopulatedTemplateRendering:
    def test_assignment_form_attachments_panel(
        self, client, teacher_fixture, course_fixture, open_assignment, open_attachment
    ):
        client.force_login(teacher_fixture)
        edit_url = reverse(
            "dashboard:teacher_course_assignment_edit",
            kwargs={"slug": course_fixture.slug, "assignment_id": open_assignment.id},
        )
        resp = client.get(edit_url)
        assert resp.status_code == 200
        html = resp.content.decode()

        assert "Attachments & Starter Files" in html
        assert open_attachment.title in html
        assert "Upload New Attachment" in html
        assert "Move Up" in html

    def test_lesson_learn_assignments_tab_and_sidebar_markers(
        self,
        client,
        student_fixture,
        active_enrollment,
        course_fixture,
        published_lesson,
        open_assignment,
    ):
        # Create course-wide assignment (no lesson attached)
        Assignment.objects.create(
            course=course_fixture,
            lesson=None,
            title="Course-Wide Final Project",
            instructions="Final project instructions.",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=10),
            is_published=True,
        )

        client.force_login(student_fixture)
        lesson_url = reverse(
            "learn:lesson",
            kwargs={"course_slug": course_fixture.slug, "lesson_id": published_lesson.id},
        )
        resp = client.get(lesson_url)
        assert resp.status_code == 200
        html = resp.content.decode()

        # Lesson assignment listed
        assert open_assignment.title in html
        # Clearly labelled Course-wide assignments section
        assert "Course-wide Assignments" in html or "Course-wide assignments" in html
        assert "Course-Wide Final Project" in html
        # Sidebar assignment badge indicator
        assert 'title="Includes assignment"' in html or "Includes assignment" in html

    def test_student_dashboard_enrolled_course_card_has_assignments_link(
        self, client, student_fixture, active_enrollment, course_fixture
    ):
        client.force_login(student_fixture)
        dash_url = reverse("dashboard:student")
        resp = client.get(dash_url)
        assert resp.status_code == 200
        html = resp.content.decode()

        expected_link = reverse("assignments:list", kwargs={"slug": course_fixture.slug})
        assert expected_link in html
        assert "Assignments" in html
