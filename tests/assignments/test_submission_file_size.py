import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment


@pytest.fixture
def file_submission_setup(db, user_factory):
    teacher = user_factory(email="prof_size@example.com", role="teacher", is_staff=True)
    student = user_factory(email="student_size@example.com", role="student")
    course = Course.objects.create(
        title="File Size Architecture",
        slug="file-size-arch",
        is_published=True,
    )
    Enrollment.objects.create(course=course, student=student, status=Enrollment.Status.ACTIVE)
    now = timezone.now()
    assignment = Assignment.objects.create(
        course=course,
        title="Storage Lab",
        instructions="Upload your solution artifact.",
        opens_at=now - timezone.timedelta(days=1),
        due_at=now + timezone.timedelta(days=5),
        max_score=100,
        is_published=True,
    )
    return teacher, student, course, assignment


@pytest.mark.django_db
def test_submission_file_size_saved_to_db_on_save(file_submission_setup):
    teacher, student, course, assignment = file_submission_setup
    payload = b"Hello, this is a 42-byte file content!"
    test_file = SimpleUploadedFile("assignment.txt", payload, content_type="text/plain")

    sub = Submission.objects.create(
        assignment=assignment,
        student=student,
        content_text="Attached is my laboratory file.",
        original_filename="assignment.txt",
        file=test_file,
    )

    # Reload directly from DB with only file_size field selected
    fresh_sub = Submission.objects.filter(pk=sub.pk).values("file_size").get()
    assert fresh_sub["file_size"] == len(payload)
    assert sub.file_size == len(payload)


@pytest.mark.django_db
def test_submission_clearing_file_clears_file_size(file_submission_setup):
    teacher, student, course, assignment = file_submission_setup
    test_file = SimpleUploadedFile("lab.txt", b"ABCDE", content_type="text/plain")

    sub = Submission.objects.create(
        assignment=assignment,
        student=student,
        content_text="First draft with file",
        file=test_file,
    )
    assert sub.file_size == 5

    # Edit to remove file
    sub.file = None
    sub.save()

    fresh_sub = Submission.objects.filter(pk=sub.pk).values("file_size").get()
    assert fresh_sub["file_size"] is None


@pytest.mark.django_db
def test_submission_file_size_used_in_teacher_grading_page_without_storage_call(client, file_submission_setup):
    teacher, student, course, assignment = file_submission_setup
    payload = b"X" * 1024  # 1.0 KB
    test_file = SimpleUploadedFile("lab_report.pdf", payload, content_type="application/pdf")

    sub = Submission.objects.create(
        assignment=assignment,
        student=student,
        content_text="Check my PDF.",
        original_filename="lab_report.pdf",
        file=test_file,
    )
    assert sub.file_size == 1024

    client.force_login(teacher)
    url = reverse("dashboard:teacher_submission_grade", kwargs={"submission_id": sub.id})
    resp = client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "1.0\xa0KB" in html or "1.0 KB" in html or "1024" in html
    assert "lab_report.pdf" in html


@pytest.mark.django_db
def test_backfill_file_sizes_tolerates_missing_files(file_submission_setup, caplog):
    """The migration backfill function must tolerate missing or unreadable files (skip and log)."""
    import importlib
    from django.apps import apps
    migration_mod = importlib.import_module("apps.assignments.migrations.0005_submission_file_size")
    backfill_file_sizes = migration_mod.backfill_file_sizes

    teacher, student, course, assignment = file_submission_setup
    sub = Submission.objects.create(
        assignment=assignment,
        student=student,
        content_text="Missing file submission",
        file="assignments/submissions/nonexistent_file_xyz123.pdf",
    )
    # Ensure file_size is None initially
    Submission.objects.filter(pk=sub.pk).update(file_size=None)

    # Execute backfill
    import logging
    with caplog.at_level(logging.WARNING):
        backfill_file_sizes(apps, None)

    sub.refresh_from_db()
    assert sub.file_size is None
    assert any("Skipping file_size backfill for submission" in record.message for record in caplog.records)
