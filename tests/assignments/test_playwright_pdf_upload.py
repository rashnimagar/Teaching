import os
from pathlib import Path

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment

playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright


def generate_valid_pdf_bytes():
    stream_content = b"BT /F1 12 Tf 72 712 Td (Student Assignment Solution) Tj ET"
    stream_len = len(stream_content)
    pdf = (
        b"%PDF-1.4\n"
        b"%\xe2\xe3\xcf\xd3\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length "
        + str(stream_len).encode("ascii")
        + b" >>\nstream\n"
        + stream_content
        + b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000015 00000 n \n0000000068 00000 n \n0000000125 00000 n \n0000000248 00000 n \n0000000350 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n430\n%%EOF\n"
    )
    return pdf


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
def test_student_upload_real_pdf_playwright(live_server, user_factory, tmp_path):
    teacher = user_factory(
        email="teacher_test@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )
    EmailAddress.objects.create(user=teacher, email=teacher.email, primary=True, verified=True)

    student = user_factory(
        email="student_test@example.com",
        role=User.Role.STUDENT,
    )
    EmailAddress.objects.create(user=student, email=student.email, primary=True, verified=True)

    course = Course.objects.create(
        title="Web Testing Course",
        slug="web-testing-course",
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
        title="Term Project Report",
        instructions="Upload your comprehensive term project report.",
        opens_at=now - timezone.timedelta(days=1),
        due_at=now + timezone.timedelta(days=5),
        max_score=100,
        is_published=True,
    )

    # Save real PDF to temporary file
    real_pdf_path = tmp_path / "term_paper.pdf"
    real_pdf_path.write_bytes(generate_valid_pdf_bytes())

    chrome_exe = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "ms-playwright"
        / "chromium-1248"
        / "chrome-win64"
        / "chrome.exe"
    )
    launch_kwargs = {"headless": True}
    if chrome_exe.exists():
        launch_kwargs["executable_path"] = str(chrome_exe)

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page()

        # Login as student
        page.goto(f"{live_server.url}/accounts/login/")
        page.fill('input[name="login"]', "student_test@example.com")
        page.fill('input[name="password"]', "TestPassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # Navigate to open assignment detail page
        assign_url = f"{live_server.url}{reverse('assignments:detail', kwargs={'slug': course.slug, 'assignment_id': assignment.id})}"
        page.goto(assign_url)
        page.wait_for_load_state("networkidle")

        # 1. Check visible file chooser
        file_input = page.locator("#file_upload")
        assert file_input.is_visible(), "File chooser input #file_upload must be visible"

        # 2. Check form enctype
        form = page.locator("form[data-submit-protect]")
        enctype = form.get_attribute("enctype")
        assert enctype == "multipart/form-data", f"Expected multipart/form-data, got {enctype}"

        # 3. Choose real PDF file
        file_input.set_input_files(str(real_pdf_path))

        # Submit the form
        page.click("#assignment-submit-btn")
        page.wait_for_load_state("networkidle")

        # Check result
        submission = Submission.objects.filter(assignment=assignment, student=student).first()
        print("Submission found:", submission)
        if submission:
            print("Submission file:", submission.file.name, "size:", submission.file_size)
        else:
            # Check if there is an error message on the page
            error_elem = page.locator("[role='alert']")
            error_text = error_elem.text_content() if error_elem.count() > 0 else "No alert found"
            print("Page alert:", error_text)

        assert submission is not None, "Submission should be saved in DB"
        assert submission.file, "Submission file should be saved"

        # Check teacher grading page sees the submission
        browser.close()

    # Teacher context
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page()

        page.goto(f"{live_server.url}/accounts/login/")
        page.fill('input[name="login"]', "teacher_test@example.com")
        page.fill('input[name="password"]', "TestPassword123!")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # 1. Check assignment submissions list
        submissions_url = f"{live_server.url}{reverse('dashboard:teacher_course_assignment_submissions', kwargs={'slug': course.slug, 'assignment_id': assignment.id})}"
        page.goto(submissions_url)
        page.wait_for_load_state("networkidle")
        content = page.content()
        assert "student_test@example.com" in content, "Submissions list must show student email"

        # 2. Check submission grade view
        grade_url = f"{live_server.url}{reverse('dashboard:teacher_submission_grade', kwargs={'submission_id': submission.id})}"
        page.goto(grade_url)
        page.wait_for_load_state("networkidle")
        grade_content = page.content()
        assert (
            "term_paper.pdf" in grade_content
            or "Attached Document" in grade_content
            or "Download" in grade_content
        ), "Teacher grade view must show student's submitted file"
        browser.close()
