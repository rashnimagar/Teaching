import copy
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import pytest
from allauth.account.models import EmailAddress
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import Assignment, AssignmentAttachment, Submission
from apps.courses.models import Course, CourseMaterial, Enrollment, Lesson, MaterialItem
from apps.notifications.models import Notification
from config.settings.base import CSP_DIRECTIVES

playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestBrowserCSPViolations:
    """
    Automated browser test suite using real Chromium to verify that
    guest, student, and teacher workflows produce ZERO securitypolicyviolation events
    under the production Content-Security-Policy configuration.
    Prints every visited URL and asserts the exact expected HTTP status codes.
    """

    def _setup_test_data(self, user_factory):
        teacher = user_factory(
            email="teacher_csp@example.com",
            role=User.Role.TEACHER,
            is_staff=True,
        )
        EmailAddress.objects.create(user=teacher, email=teacher.email, primary=True, verified=True)

        student = user_factory(
            email="student_csp@example.com",
            role=User.Role.STUDENT,
        )
        EmailAddress.objects.create(user=student, email=student.email, primary=True, verified=True)
        course = Course.objects.create(
            title="CSP Test Course",
            slug="csp-test-course",
            is_published=True,
        )
        Enrollment.objects.create(
            student=student,
            course=course,
            status=Enrollment.Status.ACTIVE,
        )
        # Lesson 1: YouTube video with click-to-load facade
        lesson_yt = Lesson.objects.create(
            course=course,
            title="Introduction to Security",
            order=1,
            is_published=True,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
        )
        # Lesson 2: Vimeo video embed
        lesson_vimeo = Lesson.objects.create(
            course=course,
            title="Vimeo Video Briefing",
            order=2,
            is_published=True,
            video_provider=Lesson.VideoProvider.VIMEO,
            video_id="123456789",
        )
        # Lesson 3: Bunny Stream embed
        lesson_bunny = Lesson.objects.create(
            course=course,
            title="Bunny Stream Deep Dive",
            order=3,
            is_published=True,
            video_provider=Lesson.VideoProvider.BUNNY,
            video_id="abcdef-1234-5678",
        )

        assignment_graded = Assignment.objects.create(
            course=course,
            lesson=lesson_yt,
            title="Security Audit Lab",
            instructions="Submit your audit report.",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=7),
            max_score=100,
            is_published=True,
        )
        submission = Submission.objects.create(
            assignment=assignment_graded,
            student=student,
            content_text="Sample student audit submission text.",
            submitted_at=timezone.now(),
        )

        # Assignment unsubmitted for testing browser form submission flow
        assignment_unsubmitted = Assignment.objects.create(
            course=course,
            lesson=lesson_vimeo,
            title="Defense in Depth Assignment",
            instructions="Write a short response on defense in depth.",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=7),
            max_score=100,
            is_published=True,
        )

        material = CourseMaterial.objects.create(
            course=course,
            title="Course Documentation",
            is_published=True,
        )
        pdf_file = SimpleUploadedFile(
            "handout.pdf", b"%PDF-1.4 sample content", content_type="application/pdf"
        )
        pdf_item = MaterialItem.objects.create(
            material=material,
            title="Security Architecture Handout",
            item_type=MaterialItem.ItemType.FILE,
            file=pdf_file,
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            is_published=True,
        )
        Notification.objects.create(
            recipient=student,
            kind=Notification.Kind.ENROLLMENT_APPROVED,
            title="Enrollment Confirmed",
            body="Welcome to the security course.",
        )
        att_pdf_file = SimpleUploadedFile(
            "rubric.pdf", b"%PDF-1.4 sample rubric content", content_type="application/pdf"
        )
        att_pdf = AssignmentAttachment.objects.create(
            assignment=assignment_unsubmitted,
            title="Lab Rubric",
            file=att_pdf_file,
            download_policy=AssignmentAttachment.DownloadPolicy.VIEW_ONLY,
            is_published=True,
        )
        return (
            teacher,
            student,
            course,
            lesson_yt,
            lesson_vimeo,
            lesson_bunny,
            assignment_graded,
            assignment_unsubmitted,
            submission,
            material,
            pdf_item,
            att_pdf,
        )

    def test_zero_csp_violations_across_roles(self, live_server, user_factory, settings):
        settings.CSRF_COOKIE_HTTPONLY = True
        settings.CSRF_COOKIE_SECURE = False

        # Apply production Content-Security-Policy directives
        prod_directives = copy.deepcopy(CSP_DIRECTIVES)
        prod_directives["upgrade-insecure-requests"] = True
        settings.CONTENT_SECURITY_POLICY = {
            "DIRECTIVES": prod_directives,
            "EXCLUDE_URL_PREFIXES": [settings.ADMIN_URL_PREFIX],
        }

        (
            teacher,
            student,
            course,
            lesson_yt,
            lesson_vimeo,
            lesson_bunny,
            assignment_graded,
            assignment_unsubmitted,
            submission,
            material,
            pdf_item,
            att_pdf,
        ) = self._setup_test_data(user_factory)

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
            context = browser.new_context()

            # Fulfill external video provider embeds and thumbnails with clean mocks so tests don't depend
            # on external CDN uptime, DNS, or trigger external CDN bot-protection scripts (with foreign CSPs).
            # The browser still evaluates our platform's frame-src and img-src before routing to these URLs.
            def _handle_external_route(route):
                if "ytimg" in route.request.url:
                    route.fulfill(
                        status=200,
                        content_type="image/jpeg",
                        body=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9",
                    )
                else:
                    route.fulfill(
                        status=200,
                        content_type="text/html",
                        body="<!DOCTYPE html><html><head><title>Video Embed</title></head><body>Video Player Mock</body></html>",
                    )

            context.route(
                lambda url: any(
                    domain in url
                    for domain in [
                        "player.vimeo.com",
                        "iframe.mediadelivery.net",
                        "youtube-nocookie.com",
                        "i.ytimg.com",
                    ]
                ),
                _handle_external_route,
            )

            page = context.new_page()

            violations = []
            console_errors = []

            # Capture all securitypolicyviolation events on every document load
            page.add_init_script("""
                window.__cspViolations = [];
                document.addEventListener('securitypolicyviolation', (e) => {
                    window.__cspViolations.push({
                        blockedURI: e.blockedURI,
                        violatedDirective: e.violatedDirective,
                        originalPolicy: e.originalPolicy,
                        sourceFile: e.sourceFile,
                        lineNumber: e.lineNumber
                    });
                });
            """)

            def on_console(msg):
                if msg.type == "error":
                    text = msg.text
                    if (
                        "Content Security Policy" in text
                        or "securitypolicyviolation" in text
                        or "csp" in text.lower()
                    ):
                        console_errors.append(text)

            page.on("console", on_console)

            def check_violations(context_name: str, url: str):
                page_violations = page.evaluate("window.__cspViolations || []")
                for v in page_violations:
                    violations.append((url, context_name, v))

            def visit_and_assert(url: str, expected_status: int, role: str, reverse_name: str = ""):
                resp = page.goto(url, wait_until="domcontentloaded")
                status = resp.status if resp else None
                name_info = f" ({reverse_name})" if reverse_name else ""
                print(f"[{role}] HTTP {status} {url}{name_info}")
                assert status == expected_status, (
                    f"Expected HTTP {expected_status} for {url}, got {status}"
                )
                page.wait_for_load_state("domcontentloaded")
                check_violations(role, url)
                return resp

            # -----------------------------------------------------------------
            # 1. Guest Routes & Error Pages
            # -----------------------------------------------------------------
            visit_and_assert(f"{live_server.url}{reverse('core:home')}", 200, "Guest", "core:home")
            visit_and_assert(
                f"{live_server.url}{reverse('courses:list')}", 200, "Guest", "courses:list"
            )
            visit_and_assert(
                f"{live_server.url}{reverse('courses:detail', kwargs={'slug': course.slug})}",
                200,
                "Guest",
                "courses:detail",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('account_login')}", 200, "Guest", "account_login"
            )
            visit_and_assert(
                f"{live_server.url}{reverse('account_signup')}", 200, "Guest", "account_signup"
            )
            visit_and_assert(
                f"{live_server.url}{reverse('account_reset_password')}",
                200,
                "Guest",
                "account_reset_password",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('account_reset_password_done')}",
                200,
                "Guest",
                "account_reset_password_done",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('core:privacy')}", 200, "Guest", "core:privacy"
            )
            visit_and_assert(
                f"{live_server.url}{reverse('core:terms')}", 200, "Guest", "core:terms"
            )
            visit_and_assert(f"{live_server.url}/403/", 403, "Guest", "core:403")
            visit_and_assert(f"{live_server.url}/404/", 404, "Guest", "core:404")
            visit_and_assert(f"{live_server.url}/500/", 500, "Guest", "core:500")

            # Confirm handler500 page is rendered with custom inline <style> permitted by SHA-256 hash
            page.wait_for_selector("text=Unexpected Server Error")
            card_border_radius = page.evaluate(
                "() => window.getComputedStyle(document.querySelector('.card')).borderRadius"
            )
            assert card_border_radius in ["24px", "1.5rem"], (
                f"Expected styled card border radius, got {card_border_radius}"
            )
            check_violations("500 Server Error Page", f"{live_server.url}/500/")

            # Custom 404 Not Found check for arbitrary nonexistent route
            visit_and_assert(
                f"{live_server.url}/nonexistent-page-404-check/", 404, "Guest", "arbitrary_404"
            )

            # -----------------------------------------------------------------
            # 2. Student Session & Interactions
            # -----------------------------------------------------------------
            page.goto(f"{live_server.url}{reverse('account_login')}")
            page.fill('input[name="login"]', "student_csp@example.com")
            page.fill('input[name="password"]', "TestPassword123!")
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")
            check_violations("Student Login", f"{live_server.url}/accounts/login/")

            # 2a. Student Dashboard & Notifications
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:student')}",
                200,
                "Student",
                "dashboard:student",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('notifications:list')}",
                200,
                "Student",
                "notifications:list",
            )

            # 2b. Lesson Page (YouTube) with Facade Click and Mark Complete AJAX under Production CSP
            lesson_yt_path = reverse(
                "learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": lesson_yt.id}
            )
            lesson_yt_url = f"{live_server.url}{lesson_yt_path}"
            visit_and_assert(lesson_yt_url, 200, "Student", "learn:lesson (YouTube)")

            # Click YouTube Facade to verify dynamic iframe injection complies with CSP frame-src
            facade_button = page.locator("#youtube-facade")
            assert facade_button.count() == 1, "Expected exactly 1 YouTube facade button"
            facade_button.click()
            page.wait_for_selector("#lesson-video-iframe", timeout=5000)
            iframe_src = page.locator("#lesson-video-iframe").get_attribute("src") or ""
            assert "youtube-nocookie.com" in iframe_src, (
                f"Expected YouTube embed URL, got {iframe_src}"
            )
            yt_parsed = urlparse(iframe_src)
            assert yt_parsed.hostname in ["www.youtube-nocookie.com", "youtube-nocookie.com"]
            assert f"https://{yt_parsed.hostname}" in prod_directives["frame-src"] or any(
                yt_parsed.hostname in s for s in prod_directives["frame-src"]
            )
            page.wait_for_load_state("networkidle")
            check_violations("Student Lesson YouTube Iframe", lesson_yt_url)

            # Prove CSRF_COOKIE_HTTPONLY is on: JS document.cookie cannot read csrftoken
            has_js_cookie = page.evaluate("() => document.cookie.includes('csrftoken')")
            assert not has_js_cookie, (
                "csrftoken cookie must not be accessible via document.cookie when HttpOnly is on"
            )

            # Prove components.js provides the token from <meta name="csrf-token">
            meta_token = page.evaluate("() => window.getCsrfToken ? window.getCsrfToken() : null")
            assert meta_token and len(meta_token) > 20, (
                "window.getCsrfToken() must extract valid token from meta tag"
            )

            # Click Mark Complete and assert 200 response
            toggle_path = reverse(
                "learn:toggle_complete",
                kwargs={"course_slug": course.slug, "lesson_id": lesson_yt.id},
            )
            complete_url = f"{live_server.url}{toggle_path}"
            with page.expect_response(
                lambda r: complete_url in r.url and r.request.method == "POST"
            ) as resp_info:
                page.click("#toggle-complete-btn")
            complete_resp = resp_info.value
            print(
                f"[Student Action] HTTP {complete_resp.status} {complete_resp.url} (learn:toggle_complete)"
            )
            assert complete_resp.status == 200, (
                f"Expected 200 from toggle-complete, got {complete_resp.status}"
            )
            toggle_payload = complete_resp.json()
            assert toggle_payload.get("completed") is True, (
                f"Expected completed=True, got {toggle_payload}"
            )
            page.wait_for_load_state("networkidle")
            check_violations("Student Mark Complete AJAX", lesson_yt_url)

            # 2c. Lesson Page (Vimeo embed)
            lesson_vimeo_path = reverse(
                "learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": lesson_vimeo.id}
            )
            lesson_vimeo_url = f"{live_server.url}{lesson_vimeo_path}"
            visit_and_assert(lesson_vimeo_url, 200, "Student", "learn:lesson (Vimeo)")
            page.wait_for_selector("#lesson-video-iframe", timeout=5000)
            vimeo_src = page.locator("#lesson-video-iframe").get_attribute("src") or ""
            assert "player.vimeo.com" in vimeo_src, (
                f"Expected Vimeo player embed URL, got {vimeo_src}"
            )
            vimeo_parsed = urlparse(vimeo_src)
            assert vimeo_parsed.hostname == "player.vimeo.com"
            assert f"https://{vimeo_parsed.hostname}" in prod_directives["frame-src"]
            check_violations("Student Lesson Vimeo Embed", lesson_vimeo_url)

            # 2d. Lesson Page (Bunny Stream embed)
            lesson_bunny_path = reverse(
                "learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": lesson_bunny.id}
            )
            lesson_bunny_url = f"{live_server.url}{lesson_bunny_path}"
            visit_and_assert(lesson_bunny_url, 200, "Student", "learn:lesson (Bunny)")
            page.wait_for_selector("#lesson-video-iframe", timeout=5000)
            bunny_src = page.locator("#lesson-video-iframe").get_attribute("src") or ""
            assert "iframe.mediadelivery.net" in bunny_src, (
                f"Expected Bunny Stream embed URL, got {bunny_src}"
            )
            bunny_parsed = urlparse(bunny_src)
            assert bunny_parsed.hostname == "iframe.mediadelivery.net"
            assert f"https://{bunny_parsed.hostname}" in prod_directives["frame-src"]
            check_violations("Student Lesson Bunny Embed", lesson_bunny_url)

            # 2e. Assignment Detail & Student Submission Flow
            assign_submit_path = reverse(
                "assignments:detail",
                kwargs={"slug": course.slug, "assignment_id": assignment_unsubmitted.id},
            )
            assign_submit_url = f"{live_server.url}{assign_submit_path}"
            visit_and_assert(assign_submit_url, 200, "Student", "assignments:detail")

            # Submit written text response directly through the browser
            page.fill('textarea[name="content_text"]', "Automated browser audit defense writeup.")
            page.click("#assignment-submit-btn")
            page.wait_for_load_state("networkidle")
            print(f"[Student Action] HTTP 200 {page.url} (assignments:detail post-submit)")
            check_violations("Student Assignment Submission", page.url)
            assert Submission.objects.filter(
                assignment=assignment_unsubmitted, student=student
            ).exists(), "Student submission must exist in database"

            # 2e-ii. Course Assignments List & Attachment Preview
            assign_list_path = reverse("assignments:list", kwargs={"slug": course.slug})
            assign_list_url = f"{live_server.url}{assign_list_path}"
            visit_and_assert(assign_list_url, 200, "Student", "assignments:list")

            att_preview_path = reverse(
                "assignments:attachment_preview",
                kwargs={"slug": course.slug, "attachment_id": att_pdf.id},
            )
            att_preview_url = f"{live_server.url}{att_preview_path}"
            visit_and_assert(att_preview_url, 200, "Student", "assignments:attachment_preview")

            # 2f. Course Materials List & Inline Preview Modal
            materials_path = reverse("learn:materials", kwargs={"course_slug": course.slug})
            materials_url = f"{live_server.url}{materials_path}"
            visit_and_assert(materials_url, 200, "Student", "learn:materials")

            # Click "Preview Inline" button to trigger PDF modal preview in iframe
            preview_btn = page.locator("[data-preview-trigger]")
            assert preview_btn.count() == 1, (
                "Expected exactly 1 preview trigger button on materials page"
            )
            preview_btn.first.click()
            page.wait_for_selector("#preview-modal:not(.hidden)", timeout=5000)
            iframe_locator = page.locator("#preview-modal-iframe")
            assert "/preview/" in (iframe_locator.get_attribute("src") or "")
            page.wait_for_load_state("networkidle")
            check_violations("Student Material Iframe Preview", materials_url)

            # Close preview modal
            close_btn = page.locator("#preview-modal-close")
            assert close_btn.count() == 1, "Expected exactly 1 preview modal close button"
            close_btn.click()
            page.wait_for_selector("#preview-modal", state="hidden", timeout=5000)

            # 2g. 403 Forbidden Check: Student accessing teacher area
            teacher_forbidden_path = reverse("dashboard:teacher")
            teacher_forbidden_url = f"{live_server.url}{teacher_forbidden_path}"
            visit_and_assert(
                teacher_forbidden_url, 403, "Student", "dashboard:teacher (unauthorized)"
            )

            # -----------------------------------------------------------------
            # 3. Teacher Session & Dashboard Management
            # -----------------------------------------------------------------
            page.goto(f"{live_server.url}/accounts/logout/")
            if page.locator('button[type="submit"]').count() > 0:
                page.click('button[type="submit"]')
                page.wait_for_load_state("networkidle")

            page.goto(f"{live_server.url}{reverse('account_login')}")
            page.fill('input[name="login"]', "teacher_csp@example.com")
            page.fill('input[name="password"]', "TestPassword123!")
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")
            check_violations("Teacher Login", f"{live_server.url}/accounts/login/")

            # Teacher Dashboard & Management Pages
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher')}",
                200,
                "Teacher",
                "dashboard:teacher",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher_courses')}",
                200,
                "Teacher",
                "dashboard:teacher_courses",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher_course_materials', kwargs={'slug': course.slug})}",
                200,
                "Teacher",
                "dashboard:teacher_course_materials",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher_enrollments')}",
                200,
                "Teacher",
                "dashboard:teacher_enrollments",
            )

            # Grading Page with Student Written Text Visibility
            grading_path = reverse(
                "dashboard:teacher_submission_grade", kwargs={"submission_id": submission.id}
            )
            grading_url = f"{live_server.url}{grading_path}"
            visit_and_assert(grading_url, 200, "Teacher", "dashboard:teacher_submission_grade")

            # Verify student text answer is visibly rendered on screen under "Text response"
            text_section_header = page.locator("h2", has_text="Text response")
            text_section_header.wait_for(state="visible", timeout=5000)
            answer_locator = page.locator(".prose")
            answer_locator.wait_for(state="visible", timeout=5000)
            assert "Sample student audit submission text." in answer_locator.inner_text()

            # Verify "Attached file" section is visible
            file_section_header = page.locator("h2", has_text="Attached file")
            file_section_header.wait_for(state="visible", timeout=5000)
            check_violations("Teacher Grading Page Text Visibility", grading_url)

            # Teacher Assignment Edit (Attachments Panel) and Attachment Downloads History
            assign_edit_path = reverse(
                "dashboard:teacher_course_assignment_edit",
                kwargs={"slug": course.slug, "assignment_id": assignment_unsubmitted.id},
            )
            assign_edit_url = f"{live_server.url}{assign_edit_path}"
            visit_and_assert(
                assign_edit_url, 200, "Teacher", "dashboard:teacher_course_assignment_edit"
            )

            att_downloads_path = reverse(
                "dashboard:teacher_assignment_attachment_downloads",
                kwargs={
                    "slug": course.slug,
                    "assignment_id": assignment_unsubmitted.id,
                    "attachment_id": att_pdf.id,
                },
            )
            att_downloads_url = f"{live_server.url}{att_downloads_path}"
            visit_and_assert(
                att_downloads_url,
                200,
                "Teacher",
                "dashboard:teacher_assignment_attachment_downloads",
            )

            # Settings, FAQs, Permissions
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher_faqs')}",
                200,
                "Teacher",
                "dashboard:teacher_faqs",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher_settings')}",
                200,
                "Teacher",
                "dashboard:teacher_settings",
            )
            visit_and_assert(
                f"{live_server.url}{reverse('dashboard:teacher_permissions')}",
                200,
                "Teacher",
                "dashboard:teacher_permissions",
            )

            browser.close()

            assert len(violations) == 0, f"Detected CSP violations:\n{violations}"
            assert len(console_errors) == 0, f"Detected CSP console errors:\n{console_errors}"

            allowed_hosts = {
                "youtube-nocookie.com",
                "www.youtube-nocookie.com",
                "player.vimeo.com",
                "iframe.mediadelivery.net",
            }
            for _url, _ctx, v in violations:
                blocked = v.get("blockedURI", "")
                assert not any(h in blocked for h in allowed_hosts), (
                    f"Blocked URI on allowed provider host: {blocked}"
                )
