import ast
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.assignments.services.grading import grade_submission
from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadRequest,
    Enrollment,
    Lesson,
    MaterialItem,
)
from apps.courses.services.download_requests import transition_download_request
from apps.courses.services.enrollments import transition_enrollment_status
from apps.notifications.models import Notification


@pytest.fixture
def notification_test_data(db, user_factory):
    teacher = user_factory(email="teacher_notif@example.com", role="teacher", is_staff=True)
    student = user_factory(email="student_notif@example.com", role="student")

    course = Course.objects.create(
        title="Notification Systems",
        slug="notif-systems",
        is_published=True,
    )
    Lesson.objects.create(
        course=course,
        title="Welcome to Notifications",
        order=1,
        is_published=True,
    )
    material = CourseMaterial.objects.create(course=course, title="Handouts")
    dummy_file = SimpleUploadedFile("handout.pdf", b"%PDF-1.4 mock", content_type="application/pdf")
    material_item = MaterialItem.objects.create(
        material=material,
        title="Course Slides",
        item_type=MaterialItem.ItemType.FILE,
        file=dummy_file,
        download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
    )
    dummy_file2 = SimpleUploadedFile(
        "notes.pdf", b"%PDF-1.4 mock 2", content_type="application/pdf"
    )
    material_item2 = MaterialItem.objects.create(
        material=material,
        title="Course Notes",
        item_type=MaterialItem.ItemType.FILE,
        file=dummy_file2,
        download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
    )
    now = timezone.now()
    assignment = Assignment.objects.create(
        course=course,
        title="Notification Project",
        instructions="Implement robust notifications.",
        opens_at=now - timezone.timedelta(days=1),
        due_at=now + timezone.timedelta(days=7),
        max_score=100,
        is_published=True,
    )

    return {
        "teacher": teacher,
        "student": student,
        "course": course,
        "material_item": material_item,
        "material_item2": material_item2,
        "assignment": assignment,
    }


@pytest.mark.django_db
def test_all_six_notification_kinds_resolve_without_404(
    client, notification_test_data, django_capture_on_commit_callbacks
):
    teacher = notification_test_data["teacher"]
    student = notification_test_data["student"]
    course = notification_test_data["course"]
    material_item = notification_test_data["material_item"]
    material_item2 = notification_test_data["material_item2"]
    assignment = notification_test_data["assignment"]

    created_kinds = set()

    # 1 & 2: Enrollment notifications (APPROVED & REVOKED)
    enrollment = Enrollment.objects.create(
        course=course, student=student, status=Enrollment.Status.PENDING
    )
    # Trigger ACTIVE (APPROVED)
    with django_capture_on_commit_callbacks(execute=True):
        transition_enrollment_status(enrollment.id, Enrollment.Status.ACTIVE, actor=teacher)
    notif_enr_appr = Notification.objects.get(
        recipient=student, kind=Notification.Kind.ENROLLMENT_APPROVED
    )
    created_kinds.add(notif_enr_appr.kind)

    # Trigger REVOKED
    with django_capture_on_commit_callbacks(execute=True):
        transition_enrollment_status(enrollment.id, Enrollment.Status.REVOKED, actor=teacher)
    notif_enr_rev = Notification.objects.get(
        recipient=student, kind=Notification.Kind.ENROLLMENT_REVOKED
    )
    created_kinds.add(notif_enr_rev.kind)

    # Re-activate enrollment for remaining student views
    enrollment.status = Enrollment.Status.ACTIVE
    enrollment.save()

    # 3, 4, 5: Download notifications (APPROVED, DENIED, REVOKED)
    dl_req = DownloadRequest.objects.create(
        student=student,
        material_item=material_item,
        status=DownloadRequest.Status.PENDING,
    )
    with django_capture_on_commit_callbacks(execute=True):
        transition_download_request(
            dl_req,
            DownloadRequest.Status.APPROVED,
            decided_by=teacher,
            expires_at=timezone.now() + timezone.timedelta(hours=24),
        )
    notif_dl_appr = Notification.objects.get(
        recipient=student, kind=Notification.Kind.DOWNLOAD_APPROVED
    )
    created_kinds.add(notif_dl_appr.kind)

    dl_req2 = DownloadRequest.objects.create(
        student=student,
        material_item=material_item2,
        status=DownloadRequest.Status.PENDING,
    )
    with django_capture_on_commit_callbacks(execute=True):
        transition_download_request(
            dl_req2,
            DownloadRequest.Status.DENIED,
            decided_by=teacher,
            teacher_note="Please attend the live session first.",
        )
    notif_dl_den = Notification.objects.get(
        recipient=student, kind=Notification.Kind.DOWNLOAD_DENIED
    )
    created_kinds.add(notif_dl_den.kind)

    # Transition approved to revoked
    with django_capture_on_commit_callbacks(execute=True):
        transition_download_request(
            dl_req,
            DownloadRequest.Status.REVOKED,
            decided_by=teacher,
            teacher_note="Access expired.",
        )
    notif_dl_rev = Notification.objects.get(
        recipient=student, kind=Notification.Kind.DOWNLOAD_REVOKED
    )
    created_kinds.add(notif_dl_rev.kind)

    # 6: Submission graded notification
    sub = Submission.objects.create(
        assignment=assignment,
        student=student,
        content_text="Solution details.",
    )
    from decimal import Decimal

    with django_capture_on_commit_callbacks(execute=True):
        grade_submission(
            submission_id=sub.id,
            grade=Decimal("95.00"),
            feedback="Outstanding work.",
            teacher_user=teacher,
        )
    notif_graded = Notification.objects.get(
        recipient=student, kind=Notification.Kind.SUBMISSION_GRADED
    )
    created_kinds.add(notif_graded.kind)

    # Verify all 6 enum choices are represented
    all_enum_kinds = set(Notification.Kind.values)
    assert created_kinds == all_enum_kinds, (
        f"Missing tests for kinds: {all_enum_kinds - created_kinds}"
    )

    # Now verify every notification's URL resolves when visited by the student
    client.force_login(student)
    notifications = Notification.objects.filter(recipient=student)
    assert notifications.count() == 6

    for notif in notifications:
        assert notif.url, f"Notification {notif.id} ({notif.kind}) has empty URL"
        assert notif.url.startswith("/"), (
            f"Notification {notif.id} URL must start with '/': {notif.url}"
        )
        assert not notif.url.startswith("//"), (
            f"Notification {notif.id} URL must not be protocol-relative: {notif.url}"
        )

        resp = client.get(notif.url)
        # Must be 200 OK or 302/301 redirect (e.g. learn redirect to lesson), but never 404
        assert resp.status_code in (200, 301, 302), (
            f"Notification {notif.kind} URL '{notif.url}' returned unexpected HTTP {resp.status_code} (expected 200 or 302)"
        )


def test_no_services_hardcode_path_strings_for_notifications():
    """
    AST analysis ensuring no service file hard-codes a raw string or f-string
    when invoking create_notification. All notification URLs must be generated
    via django.urls.reverse().
    """
    apps_dir = Path(settings.BASE_DIR) / "apps"
    service_files = list(apps_dir.glob("**/services/*.py")) + list(apps_dir.glob("**/services.py"))
    assert len(service_files) >= 3

    checked_calls = 0

    for py_file in service_files:
        code = py_file.read_text(encoding="utf-8")
        if "create_notification" not in code:
            continue

        tree = ast.parse(code, filename=str(py_file))

        # Track local variables assigned to reverse(...) calls
        reverse_vars = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    func_name = getattr(
                        node.value.func, "id", getattr(node.value.func, "attr", None)
                    )
                    if func_name == "reverse":
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                reverse_vars.add(target.id)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = getattr(node.func, "id", getattr(node.func, "attr", None))
                if func_name == "create_notification":
                    checked_calls += 1
                    url_arg = None
                    for kw in node.keywords:
                        if kw.arg == "url":
                            url_arg = kw.value
                            break

                    assert url_arg is not None, (
                        f"File {py_file.name}: create_notification call missing 'url=' keyword arg."
                    )

                    # Ensure url_arg is not a raw string constant or f-string
                    assert not isinstance(url_arg, ast.Constant), (
                        f"File {py_file.name}: create_notification hardcodes a string literal URL: {url_arg.value!r}. "
                        "Must use reverse() instead."
                    )
                    assert not isinstance(url_arg, ast.JoinedStr), (
                        f"File {py_file.name}: create_notification hardcodes an f-string URL. "
                        "Must use reverse() instead."
                    )

                    # It must either be a Call to reverse() or a Name assigned to reverse()
                    is_direct_reverse = (
                        isinstance(url_arg, ast.Call)
                        and getattr(url_arg.func, "id", getattr(url_arg.func, "attr", None))
                        == "reverse"
                    )
                    is_reverse_var = isinstance(url_arg, ast.Name) and url_arg.id in reverse_vars

                    assert is_direct_reverse or is_reverse_var, (
                        f"File {py_file.name}: create_notification url must be a reverse() call "
                        f"or variable bound to reverse(), got {ast.dump(url_arg)}"
                    )

    assert checked_calls >= 4, (
        f"Expected to check at least 4 create_notification calls, checked {checked_calls}"
    )
