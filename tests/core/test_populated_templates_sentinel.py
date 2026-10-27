from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission, SubmissionEvent
from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadLog,
    DownloadRequest,
    Enrollment,
    EnrollmentEvent,
    Lesson,
    LessonProgress,
    MaterialItem,
)
from apps.notifications.models import Notification


@pytest.fixture
def populated_platform_data(db, user_factory):
    """
    Creates a rich, fully-populated set of records touching every model field
    across teacher dashboard and student learning spaces.
    """
    teacher = user_factory(
        email="teacher_sentinel@example.com",
        first_name="Prof",
        last_name="Sentinel",
        role="teacher",
        is_staff=True,
    )
    student = user_factory(
        email="student_sentinel@example.com",
        first_name="Aarav",
        last_name="Sharma",
        role="student",
    )

    now = timezone.now()

    # Course
    course = Course.objects.create(
        title="Comprehensive Python and Architecture",
        slug="comprehensive-python-arch",
        short_description="An intensive mastery course on enterprise patterns.",
        description="Deep dive into domain models, security, and rendering engines.",
        is_published=True,
        is_free=False,
        price=Decimal("49.99"),
        currency="USD",
    )

    # Enrollment & event
    enrollment = Enrollment.objects.create(
        student=student,
        course=course,
        status=Enrollment.Status.ACTIVE,
    )
    EnrollmentEvent.objects.create(
        enrollment=enrollment,
        actor=teacher,
        from_status=Enrollment.Status.PENDING,
        to_status=Enrollment.Status.ACTIVE,
        note="Approved student enrollment following verification.",
    )

    # Lessons & progress
    lesson1 = Lesson.objects.create(
        course=course,
        title="01 Architecture Foundations",
        order=1,
        description="Detailed notes on clean architecture and models.",
        is_published=True,
        duration=timezone.timedelta(minutes=45),
    )
    lesson2 = Lesson.objects.create(
        course=course,
        title="02 Template Sentinels",
        order=2,
        description="Testing template rendering with invalid string sentinels.",
        is_published=True,
        duration=timezone.timedelta(minutes=30),
    )
    LessonProgress.objects.create(
        student=student,
        lesson=lesson1,
        completed_at=now - timezone.timedelta(hours=2),
    )
    LessonProgress.objects.create(
        student=student,
        lesson=lesson2,
        last_position_seconds=120,
    )

    # Materials & items
    material = CourseMaterial.objects.create(
        course=course,
        title="Week 1 Reference Materials",
        lesson=lesson1,
        is_published=True,
    )
    dummy_file = SimpleUploadedFile("architecture_diagram.pdf", b"%PDF-1.4 diagram mockup", content_type="application/pdf")
    item_file = MaterialItem.objects.create(
        material=material,
        title="System Architecture Diagram",
        item_type=MaterialItem.ItemType.FILE,
        file=dummy_file,
        original_filename="architecture_diagram.pdf",
        download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
        is_published=True,
    )
    item_link = MaterialItem.objects.create(
        material=material,
        title="Official Python Documentation",
        item_type=MaterialItem.ItemType.LINK,
        external_url="https://docs.python.org/3/",
        is_published=True,
    )

    # Download request & download log
    dl_req = DownloadRequest.objects.create(
        student=student,
        material_item=item_file,
        status=DownloadRequest.Status.APPROVED,
        decided_by=teacher,
        decided_at=now,
        expires_at=now + timezone.timedelta(days=2),
        teacher_note="Approved for offline review.",
    )
    DownloadLog.objects.create(
        student=student,
        material_item=item_file,
        ip_address="127.0.0.1",
    )

    # Assignment
    assignment = Assignment.objects.create(
        course=course,
        lesson=lesson1,
        title="Lab 1: Domain Modeling",
        instructions="Implement the core aggregate roots and value objects.",
        opens_at=now - timezone.timedelta(days=2),
        due_at=now + timezone.timedelta(days=3),
        max_score=100,
        is_published=True,
    )

    # Submission with text + file + grade + event
    sub_file = SimpleUploadedFile("solution_v1.txt", b"print('domain layer initialized')", content_type="text/plain")
    submission = Submission.objects.create(
        assignment=assignment,
        student=student,
        content_text="Here is my comprehensive text answer explaining the domain design.",
        original_filename="solution_v1.txt",
        file=sub_file,
        submitted_at=now - timezone.timedelta(hours=5),
        is_late=False,
        grade=Decimal("94.50"),
        feedback="Superb separation of concerns and well-modeled aggregates.",
        graded_by=teacher,
        graded_at=now - timezone.timedelta(hours=1),
    )
    SubmissionEvent.objects.create(
        submission=submission,
        actor=teacher,
        action="graded",
        old_grade=None,
        new_grade=Decimal("94.50"),
        note="Initial grade awarded with written feedback.",
    )

    # Notifications
    Notification.objects.create(
        recipient=student,
        kind=Notification.Kind.SUBMISSION_GRADED,
        title="Assignment Graded: Lab 1",
        body="Your submission for 'Lab 1: Domain Modeling' received 94.50/100.",
        url=reverse("assignments:detail", kwargs={"slug": course.slug, "assignment_id": assignment.id}),
    )

    return {
        "teacher": teacher,
        "student": student,
        "course": course,
        "lesson1": lesson1,
        "lesson2": lesson2,
        "material": material,
        "item_file": item_file,
        "item_link": item_link,
        "assignment": assignment,
        "submission": submission,
        "dl_req": dl_req,
        "enrollment": enrollment,
    }


@pytest.mark.django_db
class TestPopulatedTemplatesRenderingSentinel:
    """
    Renders every core teacher and student page with fully-populated objects.
    Under config/settings/test.py, string_if_invalid raises AttributeError
    on any unresolved {{ variable }}.
    """

    # --- TEACHER PAGES ---

    def test_teacher_grading_page_renders_with_populated_data(self, client, populated_platform_data):
        teacher = populated_platform_data["teacher"]
        sub = populated_platform_data["submission"]
        client.force_login(teacher)

        url = reverse("dashboard:teacher_submission_grade", kwargs={"submission_id": sub.id})
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # Verify key populated model fields appear in the output
        assert "Aarav Sharma" in html or "student_sentinel@example.com" in html
        assert "Lab 1: Domain Modeling" in html
        assert "Here is my comprehensive text answer explaining the domain design." in html
        assert "solution_v1.txt" in html
        assert "94.50" in html or "94.5" in html
        assert "Superb separation of concerns" in html
        assert "Initial grade awarded" in html

    def test_teacher_student_detail_renders_with_populated_data(self, client, populated_platform_data):
        teacher = populated_platform_data["teacher"]
        student = populated_platform_data["student"]
        client.force_login(teacher)

        url = reverse("dashboard:teacher_student_detail", kwargs={"student_id": student.id})
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Aarav Sharma" in html or "student_sentinel@example.com" in html
        assert "Comprehensive Python and Architecture" in html
        assert "Lab 1: Domain Modeling" in html
        assert "System Architecture Diagram" in html

    def test_teacher_submissions_queue_renders_with_populated_data(self, client, populated_platform_data):
        teacher = populated_platform_data["teacher"]
        course = populated_platform_data["course"]
        assignment = populated_platform_data["assignment"]
        client.force_login(teacher)

        # Global queue
        resp_global = client.get(reverse("dashboard:teacher_submissions"))
        assert resp_global.status_code == 200
        html_global = resp_global.content.decode("utf-8")
        assert "Lab 1: Domain Modeling" in html_global
        assert "student_sentinel@example.com" in html_global
        assert "Here is my comprehensive text answer" in html_global

        # Per-assignment queue
        url_assign = reverse(
            "dashboard:teacher_course_assignment_submissions",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )
        resp_assign = client.get(url_assign)
        assert resp_assign.status_code == 200
        html_assign = resp_assign.content.decode("utf-8")
        assert "Lab 1: Domain Modeling" in html_assign
        assert "student_sentinel@example.com" in html_assign

    def test_teacher_courses_and_assignments_lists_render(self, client, populated_platform_data):
        teacher = populated_platform_data["teacher"]
        course = populated_platform_data["course"]
        client.force_login(teacher)

        # Course list
        resp_courses = client.get(reverse("dashboard:teacher_courses"))
        assert resp_courses.status_code == 200
        html_courses = resp_courses.content.decode("utf-8")
        assert "Comprehensive Python and Architecture" in html_courses

        # Assignments list
        resp_assigns = client.get(
            reverse("dashboard:teacher_course_assignments", kwargs={"slug": course.slug})
        )
        assert resp_assigns.status_code == 200
        html_assigns = resp_assigns.content.decode("utf-8")
        assert "Lab 1: Domain Modeling" in html_assigns

    def test_teacher_materials_permissions_and_history_render(self, client, populated_platform_data):
        teacher = populated_platform_data["teacher"]
        course = populated_platform_data["course"]
        item_file = populated_platform_data["item_file"]
        client.force_login(teacher)

        # Materials list
        resp_mat = client.get(reverse("dashboard:teacher_course_materials", kwargs={"slug": course.slug}))
        assert resp_mat.status_code == 200
        html_mat = resp_mat.content.decode("utf-8")
        assert "Week 1 Reference Materials" in html_mat
        assert "System Architecture Diagram" in html_mat

        # Permissions / download requests
        resp_perm = client.get(reverse("dashboard:teacher_permissions"))
        assert resp_perm.status_code == 200
        html_perm = resp_perm.content.decode("utf-8")
        assert "student_sentinel@example.com" in html_perm
        assert "System Architecture Diagram" in html_perm

        # Download history logs
        resp_hist = client.get(reverse("dashboard:teacher_download_history", kwargs={"item_id": item_file.id}))
        assert resp_hist.status_code == 200
        html_hist = resp_hist.content.decode("utf-8")
        assert "student_sentinel@example.com" in html_hist
        assert "System Architecture Diagram" in html_hist

    # --- STUDENT PAGES ---

    def test_student_dashboard_renders_with_populated_data(self, client, populated_platform_data):
        student = populated_platform_data["student"]
        client.force_login(student)

        resp = client.get(reverse("dashboard:student"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "Comprehensive Python and Architecture" in html
        assert "An intensive mastery course on enterprise patterns." in html

    def test_student_lesson_learn_view_renders_with_populated_data(self, client, populated_platform_data):
        student = populated_platform_data["student"]
        course = populated_platform_data["course"]
        lesson1 = populated_platform_data["lesson1"]
        client.force_login(student)

        url = reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": lesson1.id})
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "01 Architecture Foundations" in html
        assert "Detailed notes on clean architecture" in html

    def test_student_materials_list_renders_with_populated_data(self, client, populated_platform_data):
        student = populated_platform_data["student"]
        course = populated_platform_data["course"]
        client.force_login(student)

        url = reverse("learn:materials", kwargs={"course_slug": course.slug})
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "Week 1 Reference Materials" in html
        assert "System Architecture Diagram" in html
        assert "Official Python Documentation" in html

    def test_student_assignment_list_and_detail_render_with_populated_data(self, client, populated_platform_data):
        student = populated_platform_data["student"]
        course = populated_platform_data["course"]
        assignment = populated_platform_data["assignment"]
        client.force_login(student)

        # Assignment List
        url_list = reverse("assignments:list", kwargs={"slug": course.slug})
        resp_list = client.get(url_list)
        assert resp_list.status_code == 200
        html_list = resp_list.content.decode("utf-8")
        assert "Lab 1: Domain Modeling" in html_list
        assert "Max 100 Points" in html_list

        # Assignment Detail
        url_detail = reverse("assignments:detail", kwargs={"slug": course.slug, "assignment_id": assignment.id})
        resp_detail = client.get(url_detail)
        assert resp_detail.status_code == 200
        html_detail = resp_detail.content.decode("utf-8")
        assert "Lab 1: Domain Modeling" in html_detail
        assert "Implement the core aggregate roots" in html_detail
        assert "Here is my comprehensive text answer" in html_detail
        assert "solution_v1.txt" in html_detail
        assert "94.50" in html_detail or "94.5" in html_detail
        assert "Superb separation of concerns" in html_detail

    def test_student_notifications_page_renders_with_populated_data(self, client, populated_platform_data):
        student = populated_platform_data["student"]
        client.force_login(student)

        resp = client.get(reverse("notifications:list"))
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "Assignment Graded: Lab 1" in html
        assert "Your submission for &#x27;Lab 1: Domain Modeling&#x27; received 94.50/100." in html or "94.50/100" in html
