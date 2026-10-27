import re
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment

KATHMANDU_TZ = ZoneInfo("Asia/Kathmandu")


@pytest.fixture
def course_setup(user_factory):
    teacher = user_factory(
        email="teacher_text@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )
    student = user_factory(
        email="student_text@example.com",
        role=User.Role.STUDENT,
    )
    course = Course.objects.create(
        title="Python Security Course",
        slug="python-security-course",
        is_published=True,
    )
    Enrollment.objects.create(
        student=student,
        course=course,
        status=Enrollment.Status.ACTIVE,
    )
    now = timezone.now()
    assignment = Assignment.objects.create(
        course=course,
        title="Security Architecture Assignment",
        instructions="Analyze the architecture and submit written explanation.",
        max_score=Decimal("100.00"),
        opens_at=now - timedelta(days=2),
        due_at=now + timedelta(days=5),
        allow_late=True,
        is_published=True,
    )
    return {
        "teacher": teacher,
        "student": student,
        "course": course,
        "assignment": assignment,
    }


@pytest.mark.django_db
class TestSubmissionTextVisibilityEndToEnd:
    """
    End-to-end tests validating student assignment submissions through the real HTTP form
    and verifying visibility and formatting on the teacher grading page and queue.
    """

    def test_new_submission_text_visible_on_teacher_grading_page_and_queue(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        test_text = "This is my comprehensive architectural security response."
        resp = client.post(submit_url, {"content_text": test_text}, follow=True)
        assert resp.status_code == 200

        sub = Submission.objects.get(assignment=assignment, student=student)
        assert sub.content_text == test_text

        # 1. Verify Teacher Grading Page
        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        grade_resp = client.get(grading_url)
        assert grade_resp.status_code == 200
        content = grade_resp.content.decode("utf-8")

        assert "Text response" in content
        assert test_text in content
        assert "No text response" not in content
        assert "Attached file" in content
        assert "No file attached." in content
        assert "(Kathmandu)" in content
        assert "Turned in On Time" in content

        # 2. Verify Teacher Queue (Global submissions list)
        queue_url = reverse("dashboard:teacher_submissions")
        queue_resp = client.get(queue_url)
        assert queue_resp.status_code == 200
        queue_content = queue_resp.content.decode("utf-8")
        assert "Response Preview" in queue_content
        assert test_text[:40] in queue_content

        # 3. Verify Course Assignment Submissions List
        course_queue_url = reverse(
            "dashboard:teacher_course_assignment_submissions",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )
        c_queue_resp = client.get(course_queue_url)
        assert c_queue_resp.status_code == 200
        assert test_text[:40] in c_queue_resp.content.decode("utf-8")

    def test_edit_before_deadline_updates_teacher_grading_page(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        # First version
        client.post(submit_url, {"content_text": "Draft version 1"}, follow=True)
        sub = Submission.objects.get(assignment=assignment, student=student)
        assert sub.content_text == "Draft version 1"

        # Edit before deadline
        client.post(submit_url, {"content_text": "Final updated draft version 2"}, follow=True)
        sub.refresh_from_db()
        assert sub.content_text == "Final updated draft version 2"

        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        grade_resp = client.get(grading_url)
        assert grade_resp.status_code == 200
        content = grade_resp.content.decode("utf-8")

        assert "Final updated draft version 2" in content
        assert "Draft version 1" not in content

    def test_resubmission_after_unlock_visible_to_teacher(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        # 1. Initial submission
        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )
        client.post(submit_url, {"content_text": "Original solution"}, follow=True)
        sub = Submission.objects.get(assignment=assignment, student=student)

        # 2. Teacher grades it
        client.force_login(teacher)
        grade_post_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        client.post(grade_post_url, {"grade": "65.00", "feedback": "Needs more detail."})
        sub.refresh_from_db()
        assert sub.grade == Decimal("65.00")

        # 3. Teacher unlocks for resubmission
        unlock_url = reverse(
            "dashboard:teacher_submission_unlock",
            kwargs={"submission_id": sub.id},
        )
        client.post(unlock_url, {"note": "Please expand your explanation."})
        sub.refresh_from_db()
        assert sub.is_unlocked is True

        # 4. Student resubmits work
        client.force_login(student)
        client.post(submit_url, {"content_text": "Expanded corrected solution after teacher unlock."}, follow=True)
        sub.refresh_from_db()
        assert sub.content_text == "Expanded corrected solution after teacher unlock."
        assert sub.grade is None  # Reset to ungraded queue

        # 5. Teacher loads grading page and sees updated text
        client.force_login(teacher)
        grade_resp = client.get(grade_post_url)
        assert grade_resp.status_code == 200
        content = grade_resp.content.decode("utf-8")
        assert "Expanded corrected solution after teacher unlock." in content

    def test_text_plus_file_shows_both_sections(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        uploaded_file = SimpleUploadedFile("solution.txt", b"def solve(): return 42\n", content_type="text/plain")
        resp = client.post(
            submit_url,
            {"content_text": "Check out the attached Python script.", "file": uploaded_file},
            follow=True,
        )
        assert resp.status_code == 200

        sub = Submission.objects.get(assignment=assignment, student=student)
        assert sub.content_text == "Check out the attached Python script."
        assert sub.file is not None

        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        grade_resp = client.get(grading_url)
        content = grade_resp.content.decode("utf-8")

        # Both sections present
        assert "Text response" in content
        assert "Check out the attached Python script." in content
        assert "Attached file" in content
        assert "solution.txt" in content
        assert "bytes" in content.lower()
        assert "Download File" in content

    def test_file_only_shows_empty_text_state(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        uploaded_file = SimpleUploadedFile("diagram.pdf", b"%PDF-1.4 diagram mock\n")
        client.post(submit_url, {"content_text": "", "file": uploaded_file}, follow=True)

        sub = Submission.objects.get(assignment=assignment, student=student)
        assert not sub.content_text

        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        grade_resp = client.get(grading_url)
        content = grade_resp.content.decode("utf-8")

        assert "Text response" in content
        assert "No text response" in content
        assert "Attached file" in content
        assert "diagram.pdf" in content

    def test_nepali_unicode_text_preservation(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        nepali_text = "नमस्ते सर, मेरो कम्प्युटर सुरक्षा सम्बन्धी असाइनमेन्ट यहाँ छ।"
        client.post(submit_url, {"content_text": nepali_text}, follow=True)

        sub = Submission.objects.get(assignment=assignment, student=student)
        assert sub.content_text == nepali_text

        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        grade_resp = client.get(grading_url)
        content = grade_resp.content.decode("utf-8")

        assert nepali_text in content

    def test_long_answer_preserves_linebreaks_and_autolinks_urls(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        multi_paragraph_text = (
            "Paragraph One: Explaining the threat vector.\n\n"
            "Paragraph Two: Mitigation guidelines available at https://owasp.org/www-project-top-ten/.\n\n"
            "Paragraph Three: Final evaluation."
        )
        client.post(submit_url, {"content_text": multi_paragraph_text}, follow=True)

        sub = Submission.objects.get(assignment=assignment, student=student)
        assert sub.content_text == multi_paragraph_text

        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": sub.id},
        )
        grade_resp = client.get(grading_url)
        content = grade_resp.content.decode("utf-8")

        # Must auto-link URLs and preserve linebreaks
        assert '<a href="https://owasp.org/www-project-top-ten/"' in content
        assert "Paragraph One: Explaining the threat vector.<br" in content

    def test_script_and_special_characters_are_escaped(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        dangerous_payload = (
            "<script>alert('XSS-TEST')</script> & <b>bold</b> "
            "<img src=x onerror=alert(1)> and https://safe.example.com"
        )
        client.post(submit_url, {"content_text": dangerous_payload}, follow=True)

        client.force_login(teacher)
        grading_url = reverse(
            "dashboard:teacher_submission_grade",
            kwargs={"submission_id": assignment.submissions.first().id},
        )
        grade_resp = client.get(grading_url)
        content = grade_resp.content.decode("utf-8")

        # <script> must be escaped, NEVER rendered as executable tag
        assert "<script>alert('XSS-TEST')</script>" not in content
        assert "&lt;script&gt;alert(&#x27;XSS-TEST&#x27;)&lt;/script&gt;" in content or "&lt;script&gt;alert('XSS-TEST')&lt;/script&gt;" in content
        assert "&amp;" in content
        assert "&lt;b&gt;bold&lt;/b&gt;" in content
        assert "&lt;img src=x onerror=alert(1)&gt;" in content
        # Safe URL still auto-linked
        assert '<a href="https://safe.example.com"' in content

    def test_20000_character_limit_boundary(
        self, client, course_setup
    ):
        student = course_setup["student"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )

        # 1. Exactly 20,000 characters is accepted
        text_20k = "A" * 20000
        resp_valid = client.post(submit_url, {"content_text": text_20k})
        assert resp_valid.status_code == 302
        sub = Submission.objects.get(assignment=assignment, student=student)
        assert len(sub.content_text) == 20000

        # 2. 20,001 characters is rejected with 400 Bad Request
        text_20001 = "B" * 20001
        resp_invalid = client.post(submit_url, {"content_text": text_20001})
        assert resp_invalid.status_code == 400
        assert "exceeds the maximum allowed length of 20000 characters" in resp_invalid.content.decode("utf-8")

    def test_admin_readonly_and_student_views(
        self, client, course_setup
    ):
        student = course_setup["student"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        # Student submits text
        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )
        student_text = "Student personal submission answer."
        client.post(submit_url, {"content_text": student_text}, follow=True)

        # Check student's own view displays the text in the response section
        student_resp = client.get(submit_url)
        assert student_resp.status_code == 200
        student_content = student_resp.content.decode("utf-8")
        assert "Text response" in student_content
        assert student_text in student_content

        # Check Django admin has content_text in readonly_fields
        from apps.assignments.admin import SubmissionAdmin
        from django.contrib.admin.sites import AdminSite
        site = AdminSite()
        sub_admin = SubmissionAdmin(Submission, site)
        assert "content_text" in sub_admin.readonly_fields
        assert "original_filename" in sub_admin.readonly_fields

    def test_grades_csv_export_with_special_characters_and_text(
        self, client, course_setup
    ):
        student = course_setup["student"]
        teacher = course_setup["teacher"]
        course = course_setup["course"]
        assignment = course_setup["assignment"]

        # Student with special submission
        client.force_login(student)
        submit_url = reverse(
            "assignments:detail",
            kwargs={"slug": course.slug, "assignment_id": assignment.id},
        )
        client.post(submit_url, {"content_text": "=1+1 formula injection and नेपाली text"}, follow=True)

        sub = Submission.objects.get(assignment=assignment, student=student)
        sub.grade = Decimal("95.00")
        sub.save()

        client.force_login(teacher)
        export_url = reverse("dashboard:teacher_course_grades_export", kwargs={"slug": course.slug})
        resp = client.get(export_url)
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        csv_body = b"".join(resp.streaming_content).decode("utf-8")
        assert "95.00" in csv_body
