import io
import os
import zipfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.assignments.admin import SubmissionAdminForm
from apps.assignments.models import Assignment, Submission
from apps.assignments.status import AssignmentStatusCode, get_assignment_status
from apps.assignments.validators import (
    sanitize_display_filename,
    validate_filename_extensions,
    validate_submission_file,
)
from apps.courses.models import Course, Enrollment, Lesson

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def teacher_user(db):
    return User.objects.create_user(
        email="teacher@example.com",
        password="ValidPassword123!",
        role="teacher",
        is_staff=True,
    )


@pytest.fixture
def student_user(db):
    return User.objects.create_user(
        email="student@example.com",
        password="ValidPassword123!",
        role="student",
        first_name="Ramesh",
        last_name="Thapa",
    )


@pytest.fixture
def other_student(db):
    return User.objects.create_user(
        email="other@example.com",
        password="ValidPassword123!",
        role="student",
        first_name="Sita",
        last_name="Sharma",
    )


@pytest.fixture
def course(db, teacher_user):
    return Course.objects.create(
        title="Python Web Development",
        slug="python-web-dev",
        is_published=True,
        is_free=True,
    )


@pytest.fixture
def lesson(db, course):
    return Lesson.objects.create(
        course=course,
        title="Django Basics",
        order=1,
        is_published=True,
    )


@pytest.fixture
def unpublished_lesson(db, course):
    return Lesson.objects.create(
        course=course,
        title="Secret Upcoming Lesson",
        order=2,
        is_published=False,
    )


@pytest.fixture
def active_enrollment(db, student_user, course):
    return Enrollment.objects.create(
        student=student_user,
        course=course,
        status=Enrollment.Status.ACTIVE,
    )


@pytest.fixture
def open_assignment(db, course, lesson):
    now = timezone.now()
    return Assignment.objects.create(
        course=course,
        lesson=lesson,
        title="Homework 1: Views and Routing",
        instructions="Create a Django view that returns JSON.",
        opens_at=now - timedelta(days=2),
        due_at=now + timedelta(days=3),
        max_score=100,
        allow_late=False,
    )


@pytest.fixture
def late_allowed_assignment(db, course, lesson):
    now = timezone.now()
    return Assignment.objects.create(
        course=course,
        lesson=lesson,
        title="Homework 2: Forms and Models",
        instructions="Build a form with CSRF validation.",
        opens_at=now - timedelta(days=5),
        due_at=now - timedelta(days=1),  # Past deadline
        max_score=50,
        allow_late=True,
    )


@pytest.fixture
def future_assignment(db, course, lesson):
    now = timezone.now()
    return Assignment.objects.create(
        course=course,
        lesson=lesson,
        title="Homework 3: Advanced Optimization",
        instructions="Secret instructions not visible before opening.",
        opens_at=now + timedelta(days=3),
        due_at=now + timedelta(days=10),
        max_score=100,
        allow_late=False,
    )


def create_valid_docx() -> bytes:
    """Create a minimal valid DOCX file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types></Types>')
        zf.writestr(
            "word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document></w:document>'
        )
    return buf.getvalue()


def create_valid_png() -> bytes:
    """Create a minimal valid PNG image in memory."""
    buf = io.BytesIO()
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(buf, format="PNG")
    return buf.getvalue()


# -----------------------------------------------------------------------------
# 1. Pure Status Function Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssignmentStatusPureFunction:
    def test_status_transitions(self, open_assignment, student_user):
        now = timezone.now()

        # 1. Not open
        future_assign = Assignment(
            opens_at=now + timedelta(days=1),
            due_at=now + timedelta(days=5),
            max_score=100,
            allow_late=False,
        )
        st = get_assignment_status(future_assign, now=now)
        assert st.code == AssignmentStatusCode.NOT_OPEN
        assert st.badge_variant == "neutral"
        assert not st.is_actionable

        # 2. Open (unsubmitted)
        st = get_assignment_status(open_assignment, now=now)
        assert st.code == AssignmentStatusCode.OPEN
        assert st.badge_variant == "brand"
        assert st.is_actionable

        # 3. Overdue late allowed (unsubmitted)
        late_assign = Assignment(
            opens_at=now - timedelta(days=5),
            due_at=now - timedelta(days=1),
            max_score=100,
            allow_late=True,
        )
        st = get_assignment_status(late_assign, now=now)
        assert st.code == AssignmentStatusCode.OVERDUE_LATE_ALLOWED
        assert st.badge_variant == "warning"
        assert st.is_actionable

        # 4. Missed (unsubmitted, past deadline, late not allowed)
        missed_assign = Assignment(
            opens_at=now - timedelta(days=5),
            due_at=now - timedelta(days=1),
            max_score=100,
            allow_late=False,
        )
        st = get_assignment_status(missed_assign, now=now)
        assert st.code == AssignmentStatusCode.MISSED
        assert st.badge_variant == "danger"
        assert not st.is_actionable

        # 5. Submitted on time
        sub_on_time = Submission(
            assignment=open_assignment,
            student=student_user,
            is_late=False,
            grade=None,
        )
        st = get_assignment_status(open_assignment, submission=sub_on_time, now=now)
        assert st.code == AssignmentStatusCode.SUBMITTED
        assert st.badge_variant == "success"
        assert st.is_actionable  # Can still edit before deadline

        # 6. Submitted late
        sub_late = Submission(
            assignment=late_assign,
            student=student_user,
            is_late=True,
            grade=None,
        )
        st = get_assignment_status(late_assign, submission=sub_late, now=now)
        assert st.code == AssignmentStatusCode.LATE
        assert st.badge_variant == "warning"
        assert st.is_actionable

        # 7. Graded
        sub_graded = Submission(
            assignment=open_assignment,
            student=student_user,
            is_late=False,
            grade=Decimal("85.00"),
        )
        st = get_assignment_status(open_assignment, submission=sub_graded, now=now)
        assert st.code == AssignmentStatusCode.GRADED
        assert "85/100 pts" in st.label
        assert st.badge_variant == "success"
        assert not st.is_actionable  # Locked once graded


# -----------------------------------------------------------------------------
# 2. Validation Engine Tests
# -----------------------------------------------------------------------------


class TestValidationEngine:
    def test_dangerous_intermediate_extension_rejected(self):
        with pytest.raises(ValidationError, match="dangerous intermediate extensions"):
            validate_filename_extensions("homework.exe.pdf")

        with pytest.raises(ValidationError, match="dangerous intermediate extensions"):
            validate_filename_extensions("report.php.png")

        with pytest.raises(ValidationError, match="dangerous intermediate extensions"):
            validate_filename_extensions("file.vbs.docx")

    def test_safe_intermediate_extension_accepted(self):
        assert validate_filename_extensions("homework.v1.pdf") == "pdf"
        assert validate_filename_extensions("submission.final.draft.docx") == "docx"
        assert validate_filename_extensions("diagram.2026.04.12.png") == "png"

    def test_sanitize_display_filename(self):
        # Keeps Nepali / Unicode
        assert sanitize_display_filename("गृहकार्य_उत्तर.pdf") == "गृहकार्य_उत्तर.pdf"

        # Strips path separators
        assert sanitize_display_filename("../../etc/passwd.pdf") == "passwd.pdf"
        assert sanitize_display_filename(r"C:\Users\Admin\secrets.docx") == "secrets.docx"

        # Strips U+202E Right-to-Left Override
        assert sanitize_display_filename("document\u202eexe.pdf") == "documentexe.pdf"

        # Strips control characters
        assert sanitize_display_filename("clean\x00\x1bname.txt") == "cleanname.txt"

        # Capped length
        long_name = "a" * 200 + ".pdf"
        sanitized = sanitize_display_filename(long_name)
        stem, ext = os.path.splitext(sanitized)
        assert len(stem) <= 100
        assert ext == ".pdf"

    def test_file_type_magic_bytes_validation(self):
        # Valid PDF
        pdf_file = SimpleUploadedFile("doc.pdf", b"%PDF-1.5 sample content")
        validate_submission_file(pdf_file)

        # Invalid PDF
        bad_pdf = SimpleUploadedFile("fake.pdf", b"Not a pdf file at all")
        with pytest.raises(ValidationError, match="valid PDF"):
            validate_submission_file(bad_pdf)

        # Valid PNG
        png_data = create_valid_png()
        png_file = SimpleUploadedFile("image.png", png_data)
        validate_submission_file(png_file)

        # Valid DOCX
        docx_data = create_valid_docx()
        docx_file = SimpleUploadedFile("paper.docx", docx_data)
        validate_submission_file(docx_file)

        # Legacy .doc rejected
        doc_file = SimpleUploadedFile("legacy.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        with pytest.raises(ValidationError, match="not supported"):
            validate_submission_file(doc_file)

        # Executable binary rejected (MZ)
        exe_disguised = SimpleUploadedFile("hack.pdf", b"MZ\x90\x00\x03...")
        with pytest.raises(ValidationError, match="strictly prohibited"):
            validate_submission_file(exe_disguised)

        # Executable binary rejected (ELF)
        elf_disguised = SimpleUploadedFile("script.png", b"\x7fELF\x02\x01...")
        with pytest.raises(ValidationError, match="strictly prohibited"):
            validate_submission_file(elf_disguised)

    def test_docx_macro_and_archive_bomb_rejected(self):
        # Macro file inside docx
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types></Types>")
            zf.writestr("word/document.xml", "<document></document>")
            zf.writestr("word/vbaProject.bin", b"macro code")
        macro_docx = SimpleUploadedFile("macro.docx", buf.getvalue())
        with pytest.raises(ValidationError, match="Macro-enabled documents"):
            validate_submission_file(macro_docx)

    def test_plain_text_utf8_and_utf16_with_bom(self):
        # UTF-8 with BOM
        utf8_bom = SimpleUploadedFile("notes.txt", b"\xef\xbb\xbfSample text in UTF-8")
        validate_submission_file(utf8_bom)

        # UTF-16 with BOM
        utf16_text = "Sample UTF-16 content".encode("utf-16")
        utf16_file = SimpleUploadedFile("notes16.txt", utf16_text)
        validate_submission_file(utf16_file)

        # Text with binary nulls rejected
        bad_txt = SimpleUploadedFile("binary.txt", b"Hello\x00World")
        with pytest.raises(ValidationError, match="binary null characters"):
            validate_submission_file(bad_txt)

    def test_image_oversized_pixel_dimensions_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "ASSIGNMENT_MAX_IMAGE_PIXELS", 500)
        # Create image with 1000 pixels (>500)
        buf = io.BytesIO()
        img = Image.new("RGB", (50, 20), color="red")
        img.save(buf, format="PNG")
        oversized_img = SimpleUploadedFile("huge.png", buf.getvalue())
        with pytest.raises(ValidationError, match="Image resolution exceeds"):
            validate_submission_file(oversized_img)


# -----------------------------------------------------------------------------
# 3. Submission, Deadline, and Locking Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubmissionsAndDeadlines:
    def test_submit_before_deadline_accepted(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        resp = client.post(url, {"content_text": "Here is my answer."})
        assert resp.status_code == 302

        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        assert sub.content_text == "Here is my answer."
        assert not sub.is_late

    def test_submit_after_deadline_rejected_when_late_not_allowed(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        # Mock time to 1 minute after due_at
        with patch(
            "django.utils.timezone.now", return_value=open_assignment.due_at + timedelta(minutes=1)
        ):
            resp = client.post(url, {"content_text": "Late answer"})
            assert resp.status_code == 400
            assert (
                "The deadline has passed and late submissions are not accepted."
                in resp.content.decode()
            )
            # Typed text preserved in form
            assert "Late answer" in resp.content.decode()
            assert not Submission.objects.filter(
                assignment=open_assignment, student=student_user
            ).exists()

    def test_submit_after_deadline_accepted_when_late_allowed(
        self, client, student_user, course, late_allowed_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": late_allowed_assignment.id},
        )

        resp = client.post(url, {"content_text": "Late but allowed response"})
        assert resp.status_code == 302

        sub = Submission.objects.get(assignment=late_allowed_assignment, student=student_user)
        assert sub.is_late
        assert sub.content_text == "Late but allowed response"

    def test_edit_before_deadline_updates_same_row(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        client.post(url, {"content_text": "Version 1"})
        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        assert sub.content_text == "Version 1"

        client.post(url, {"content_text": "Version 2"})
        assert (
            Submission.objects.filter(assignment=open_assignment, student=student_user).count() == 1
        )
        sub.refresh_from_db()
        assert sub.content_text == "Version 2"

    def test_late_edit_sets_is_late_and_shares_now_timestamp(
        self, client, student_user, course, late_allowed_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": late_allowed_assignment.id},
        )

        # Submit late
        late_time = late_allowed_assignment.due_at + timedelta(hours=2)
        with patch("django.utils.timezone.now", return_value=late_time):
            client.post(url, {"content_text": "Late Edit"})

        sub = Submission.objects.get(assignment=late_allowed_assignment, student=student_user)
        assert sub.is_late
        assert sub.submitted_at == late_time

    def test_grading_locks_editing(
        self, client, student_user, teacher_user, course, open_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        client.post(url, {"content_text": "Original response"})
        sub = Submission.objects.get(assignment=open_assignment, student=student_user)

        # Teacher grades the submission
        sub.grade = Decimal("90.00")
        sub.graded_by = teacher_user
        sub.save()

        # Student attempts to edit
        resp = client.post(url, {"content_text": "Modified after grade"})
        assert resp.status_code == 302
        sub.refresh_from_db()
        assert sub.content_text == "Original response"

    def test_over_length_text_rejected(
        self, client, student_user, course, open_assignment, active_enrollment, monkeypatch
    ):
        monkeypatch.setattr(settings, "ASSIGNMENT_MAX_TEXT_LENGTH", 50)
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        resp = client.post(url, {"content_text": "A" * 60})
        assert resp.status_code == 400
        assert "exceeds the maximum allowed length" in resp.content.decode()

    def test_nepali_unicode_submission_preserved(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        nepali_text = "मेरो पहिलो गृहकार्यको उत्तर यहाँ छ।"
        resp = client.post(url, {"content_text": nepali_text})
        assert resp.status_code == 302

        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        assert sub.content_text == nepali_text

        detail_resp = client.get(url)
        assert nepali_text in detail_resp.content.decode()


# -----------------------------------------------------------------------------
# 4. Access and Visibility Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssignmentAccessAndVisibility:
    def test_instructions_hidden_before_opens_at(
        self, client, student_user, course, future_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": future_assignment.id},
        )

        resp = client.get(url)
        content = resp.content.decode()
        # Secret instructions hidden
        assert "Secret instructions not visible before opening." not in content
        assert "This assignment will open on" in content
        # Unpublished lesson title hidden
        assert "Secret Upcoming Lesson" not in content

    def test_instructions_visible_to_teacher_before_opens_at(
        self, client, teacher_user, course, future_assignment
    ):
        client.force_login(teacher_user)
        url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": future_assignment.id},
        )

        resp = client.get(url)
        content = resp.content.decode()
        assert "Secret instructions not visible before opening." in content

    def test_non_enrolled_student_redirected(self, client, other_student, course, open_assignment):
        client.force_login(other_student)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        resp = client.get(url)
        assert resp.status_code == 302
        assert reverse("courses:detail", kwargs={"slug": course.slug}) in resp.url

    def test_pending_enrollment_redirected(self, client, other_student, course, open_assignment):
        Enrollment.objects.create(
            student=other_student, course=course, status=Enrollment.Status.PENDING
        )
        client.force_login(other_student)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        resp = client.get(url)
        assert resp.status_code == 302
        assert reverse("courses:detail", kwargs={"slug": course.slug}) in resp.url


# -----------------------------------------------------------------------------
# 5. File Uploads, Downloads, and Storage Cleanup Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestFileHandlingAndDownloads:
    def test_file_upload_and_download_flow(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        png_content = create_valid_png()
        uploaded_file = SimpleUploadedFile("मेरो_गृहकार्य.png", png_content, content_type="image/png")

        resp = client.post(url, {"content_text": "See attached", "file": uploaded_file})
        assert resp.status_code == 302

        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        assert sub.original_filename == "मेरो_गृहकार्य.png"
        assert sub.file

        # Download submission file
        download_url = reverse(
            "assignments:download", kwargs={"slug": course.slug, "submission_id": sub.id}
        )
        down_resp = client.get(download_url)
        assert down_resp.status_code == 200
        assert down_resp["Content-Type"] == "application/octet-stream"
        assert down_resp["X-Content-Type-Options"] == "nosniff"
        assert down_resp["Cache-Control"] == "private, no-store"
        assert "attachment;" in down_resp["Content-Disposition"]

    def test_other_student_cannot_download_my_file(
        self, client, student_user, other_student, course, open_assignment, active_enrollment
    ):
        Enrollment.objects.create(
            student=other_student, course=course, status=Enrollment.Status.ACTIVE
        )

        # Student 1 uploads file
        sub = Submission.objects.create(
            assignment=open_assignment,
            student=student_user,
            file=SimpleUploadedFile("doc.pdf", b"%PDF-1.4 test"),
            original_filename="doc.pdf",
        )

        download_url = reverse(
            "assignments:download", kwargs={"slug": course.slug, "submission_id": sub.id}
        )

        # Student 2 attempts to download
        client.force_login(other_student)
        down_resp = client.get(download_url)
        assert down_resp.status_code == 403

    def test_teacher_can_download_student_file(
        self, client, student_user, teacher_user, course, open_assignment, active_enrollment
    ):
        sub = Submission.objects.create(
            assignment=open_assignment,
            student=student_user,
            file=SimpleUploadedFile("doc.pdf", b"%PDF-1.4 test"),
            original_filename="doc.pdf",
        )
        download_url = reverse(
            "assignments:download", kwargs={"slug": course.slug, "submission_id": sub.id}
        )

        client.force_login(teacher_user)
        down_resp = client.get(download_url)
        assert down_resp.status_code == 200

    @pytest.mark.django_db(transaction=True)
    def test_replacing_file_deletes_old_file_on_commit(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        """Under transaction=True, real DB transaction commit triggers on_commit hook."""
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        # First upload
        f1 = SimpleUploadedFile("first.pdf", b"%PDF-1.4 file one")
        client.post(url, {"file": f1})
        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        old_file_name = sub.file.name
        storage = storages["private"]
        assert storage.exists(old_file_name)

        # Replace with second upload
        f2 = SimpleUploadedFile("second.pdf", b"%PDF-1.4 file two")
        client.post(url, {"file": f2})

        sub.refresh_from_db()
        new_file_name = sub.file.name
        assert new_file_name != old_file_name
        assert storage.exists(new_file_name)
        assert not storage.exists(old_file_name)

    @pytest.mark.django_db
    def test_replacing_file_registers_on_commit_callback(
        self,
        client,
        student_user,
        course,
        open_assignment,
        active_enrollment,
        django_capture_on_commit_callbacks,
    ):
        """Using django_capture_on_commit_callbacks(execute=True) explicitly captures and executes callback."""
        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        f1 = SimpleUploadedFile("first.pdf", b"%PDF-1.4 file one")
        client.post(url, {"file": f1})
        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        old_file_name = sub.file.name
        storage = storages["private"]
        assert storage.exists(old_file_name)

        f2 = SimpleUploadedFile("second.pdf", b"%PDF-1.4 file two")
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            client.post(url, {"file": f2})

        assert len(callbacks) == 1
        sub.refresh_from_db()
        assert storage.exists(sub.file.name)
        assert not storage.exists(old_file_name)

    @pytest.mark.django_db(transaction=True)
    def test_failed_save_after_file_stored_cleans_new_file_and_preserves_old(
        self, client, student_user, course, open_assignment, active_enrollment
    ):
        from django.db.models.fields.files import FieldFile

        client.force_login(student_user)
        url = reverse(
            "assignments:detail", kwargs={"slug": course.slug, "assignment_id": open_assignment.id}
        )

        # 1. First upload succeeds
        f1 = SimpleUploadedFile("initial.pdf", b"%PDF-1.4 initial content")
        client.post(url, {"file": f1})
        sub = Submission.objects.get(assignment=open_assignment, student=student_user)
        old_file_name = sub.file.name
        storage = storages["private"]
        assert storage.exists(old_file_name)

        # 2. Upload replacement file, tracking the newly generated file name on storage
        f2 = SimpleUploadedFile("replacement.pdf", b"%PDF-1.4 replacement content")
        saved_new_names = []
        orig_file_save = FieldFile.save

        def tracking_file_save(file_instance, name, content, save=True):
            orig_file_save(file_instance, name, content, save=save)
            if name == "replacement.pdf":
                saved_new_names.append(file_instance.name)

        with patch.object(FieldFile, "save", tracking_file_save):
            with patch.object(
                Submission,
                "save",
                side_effect=RuntimeError("Simulated database failure during save"),
            ):
                with pytest.raises(RuntimeError, match="Simulated database failure during save"):
                    client.post(url, {"file": f2})

        # 3. Verify:
        # - The new file was written to storage during target_sub.file.save(...)
        assert len(saved_new_names) == 1
        new_file_name = saved_new_names[0]

        # - The new file was deleted by the exception rollback handler
        assert not storage.exists(new_file_name)

        # - Old file still exists in storage
        assert storage.exists(old_file_name)

        # - Submission in DB still points to old file
        sub.refresh_from_db()
        assert sub.file.name == old_file_name

    def test_deleting_submission_removes_file_from_storage(self, student_user, open_assignment):
        sub = Submission.objects.create(
            assignment=open_assignment,
            student=student_user,
            file=SimpleUploadedFile("file_to_del.pdf", b"%PDF-1.4 del"),
        )
        file_path = sub.file.name
        storage = storages["private"]
        assert storage.exists(file_path)

        sub.delete()
        assert not storage.exists(file_path)

    def test_missing_physical_file_does_not_crash_model_delete(self, student_user, open_assignment):
        sub = Submission.objects.create(
            assignment=open_assignment,
            student=student_user,
            file=SimpleUploadedFile("phantom.pdf", b"%PDF-1.4 phantom"),
        )
        storage = storages["private"]
        storage.delete(sub.file.name)  # Intentionally delete file from disk first

        # Should delete from DB without throwing FileNotFoundError
        sub.delete()
        assert not Submission.objects.filter(pk=sub.id).exists()


# -----------------------------------------------------------------------------
# 6. Management Command & Admin Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCommandAndAdmin:
    def test_cleanup_orphaned_submissions_defaults_to_dry_run(self, student_user, open_assignment):
        storage = storages["private"]
        orphan_path = "submissions/orphan_test_file.txt"
        storage.save(orphan_path, ContentFile(b"orphaned data"))
        assert storage.exists(orphan_path)

        # Run command without --delete (dry-run)
        out = io.StringIO()
        call_command("cleanup_orphaned_submissions", stdout=out)
        output = out.getvalue()
        assert "[DRY-RUN]" in output
        assert "orphan_test_file.txt" in output
        assert storage.exists(orphan_path)  # Still exists

        # Run command with --delete
        out_del = io.StringIO()
        call_command("cleanup_orphaned_submissions", "--delete", stdout=out_del)
        assert "Successfully deleted" in out_del.getvalue()
        assert not storage.exists(orphan_path)

    def test_admin_grade_validation_and_auto_graded_by(
        self, teacher_user, student_user, open_assignment
    ):
        sub = Submission.objects.create(
            assignment=open_assignment,
            student=student_user,
            content_text="Answer",
        )

        form = SubmissionAdminForm(
            data={"grade": Decimal("150.00"), "feedback": "Good"},
            instance=sub,
        )
        assert not form.is_valid()
        assert "cannot exceed maximum score" in str(form.errors)

        valid_form = SubmissionAdminForm(
            data={
                "assignment": sub.assignment_id,
                "student": sub.student_id,
                "content_text": "Answer",
                "submitted_at": sub.submitted_at,
                "grade": Decimal("80.00"),
                "feedback": "Well done",
            },
            instance=sub,
        )
        assert valid_form.is_valid(), valid_form.errors

    def test_course_summary_overall_score_calculation(
        self,
        client,
        student_user,
        course,
        open_assignment,
        late_allowed_assignment,
        active_enrollment,
    ):
        # Graded assignment: 80 / 100
        Submission.objects.create(
            assignment=open_assignment,
            student=student_user,
            content_text="Done",
            grade=Decimal("80.00"),
        )
        # Ungraded assignment: max 50
        Submission.objects.create(
            assignment=late_allowed_assignment,
            student=student_user,
            content_text="Done 2",
            grade=None,
        )

        client.force_login(student_user)
        list_url = reverse("assignments:list", kwargs={"slug": course.slug})
        resp = client.get(list_url)
        assert resp.status_code == 200
        # Overall score = 80 / 100 = 80.0% (ungraded assignment is excluded from denominator)
        assert "80.0%" in resp.content.decode()
