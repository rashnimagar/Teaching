import base64
import hashlib
import re
import time
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import FileResponse, HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.core.middleware import SecurityHeadersMiddleware, SessionIdleTimeoutMiddleware
from apps.core.views import get_500_style_hash, handler500
from apps.courses.models import Course, CourseMaterial, DownloadRequest, Enrollment, MaterialItem


@pytest.mark.django_db
class TestSecurityHeaders:
    """Automated verification of Phase 8A security headers and CSP enforcement."""

    def test_enforced_csp_present_on_public_pages(self, client: Client):
        """Content-Security-Policy must be present and enforced on all public pages."""
        for path in ["/", "/accounts/login/", "/accounts/signup/", "/courses/"]:
            resp = client.get(path)
            assert resp.status_code in (200, 302)
            csp = resp.headers.get("Content-Security-Policy")
            assert csp is not None, f"Enforced CSP missing on {path}"
            assert "default-src 'self'" in csp
            assert "script-src 'self'" in csp
            assert "style-src 'self'" in csp
            assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0], (
                "script-src must not allow 'unsafe-inline'"
            )
            assert "https://www.youtube-nocookie.com" in csp
            assert "https://player.vimeo.com" in csp
            assert "https://iframe.mediadelivery.net" in csp
            assert "frame-ancestors 'none'" in csp
            assert "vimeocdn.com" not in csp, "vimeocdn must not be present in CSP img-src"

    def test_django_admin_excluded_from_csp(self, client: Client):
        """
        Django Admin relies on inline scripts and styles.
        It is excluded from CSP via EXCLUDE_URL_PREFIXES and protected via rate-limiting/auth.
        """
        for path in ["/admin/", "/admin/login/"]:
            resp = client.get(path)
            assert "Content-Security-Policy" not in resp.headers, (
                f"Admin path {path} must be excluded from CSP"
            )
            assert "Content-Security-Policy-Report-Only" not in resp.headers

    def test_permissions_policy_header(self, client: Client):
        """Permissions-Policy disables risky device APIs and delegates video features."""
        resp = client.get("/")
        perm_policy = resp.headers.get("Permissions-Policy")
        assert perm_policy is not None, "Permissions-Policy header must be present"
        assert "camera=()" in perm_policy
        assert "microphone=()" in perm_policy
        assert "geolocation=()" in perm_policy
        assert "payment=()" in perm_policy
        assert "usb=()" in perm_policy
        assert "fullscreen=" in perm_policy
        assert "https://www.youtube-nocookie.com" in perm_policy
        assert "https://player.vimeo.com" in perm_policy
        assert "https://iframe.mediadelivery.net" in perm_policy

    def test_coop_header(self, client: Client):
        """Cross-Origin-Opener-Policy must isolate browsing context (same-origin)."""
        resp = client.get("/")
        assert resp.headers.get("Cross-Origin-Opener-Policy") == "same-origin"

    def test_x_content_type_options(self, client: Client):
        """X-Content-Type-Options: nosniff prevents MIME sniffing."""
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_material_preview_isolated_frame_headers(self, client: Client, user_factory):
        """
        Only material preview routes permit SAMEORIGIN framing and frame-src 'self'.
        All other routes strictly forbid framing via frame-ancestors 'none'.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.courses.models import Course, CourseMaterial, Enrollment, MaterialItem

        student = user_factory(role=User.Role.STUDENT)
        course = Course.objects.create(
            title="Secured Course",
            slug="secured-course",
            is_published=True,
        )
        Enrollment.objects.create(student=student, course=course)

        mat = CourseMaterial.objects.create(course=course, title="Sec Section", is_published=True)
        pdf_file = SimpleUploadedFile(
            "sample.pdf", b"%PDF-1.4 sample pdf content", content_type="application/pdf"
        )
        item = MaterialItem.objects.create(
            material=mat,
            title="View Only Doc",
            item_type=MaterialItem.ItemType.FILE,
            file=pdf_file,
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            is_published=True,
        )

        client.force_login(student)
        preview_url = reverse(
            "learn:material_preview", kwargs={"course_slug": course.slug, "item_id": item.id}
        )
        resp = client.get(preview_url)

        assert resp.status_code == 200
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'self'" in csp
        assert "frame-src" in csp and "'self'" in csp.split("frame-src")[1].split(";")[0]

        # Verify regular course page has frame-ancestors 'none' and NOT SAMEORIGIN
        reg_resp = client.get(f"/courses/{course.slug}/")
        assert reg_resp.headers.get("X-Frame-Options") != "SAMEORIGIN"
        reg_csp = reg_resp.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in reg_csp

    def test_admin_exclusion_matches_setting(self):
        """CSP exclusion prefix must strictly match DJANGO_ADMIN_URL setting."""
        expected_prefix = f"/{settings.DJANGO_ADMIN_URL.strip('/')}/"
        assert expected_prefix in settings.CONTENT_SECURITY_POLICY["EXCLUDE_URL_PREFIXES"]

    def test_material_preview_refuses_request_required_without_approved_request(
        self, client: Client, user_factory
    ):
        """Material preview must return 403 Forbidden for request_required files without approved request."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.courses.models import Course, CourseMaterial, Enrollment, MaterialItem

        student = user_factory(role=User.Role.STUDENT)
        course = Course.objects.create(
            title="Policy Course", slug="policy-course", is_published=True
        )
        Enrollment.objects.create(student=student, course=course)
        mat = CourseMaterial.objects.create(
            course=course, title="Restricted Sec", is_published=True
        )
        item = MaterialItem.objects.create(
            material=mat,
            title="Restricted PDF",
            item_type=MaterialItem.ItemType.FILE,
            file=SimpleUploadedFile(
                "req.pdf", b"%PDF-1.4 restricted", content_type="application/pdf"
            ),
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            is_published=True,
        )

        client.force_login(student)
        url = reverse(
            "learn:material_preview", kwargs={"course_slug": course.slug, "item_id": item.id}
        )
        resp = client.get(url)
        assert resp.status_code == 403

    def test_material_preview_policy_matrix(self, client: Client, user_factory):
        """
        Policy matrix for material in-browser preview:
        - view_only files: preview 200 for active enrolled students without any request.
        - open_to_enrolled files: preview 200 for active enrolled students without any request.
        - request_required files: preview refused (403) even with an approved request.
        - pending enrolled students: refused (403).
        - revoked enrolled students: refused (403).
        - non-enrolled students: refused (403).
        - Response headers: X-Content-Type-Options: nosniff, Cache-Control: private, no-store,
          X-Frame-Options: SAMEORIGIN, CSP frame-ancestors 'self'.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.courses.models import (
            Course,
            CourseMaterial,
            Enrollment,
            MaterialItem,
        )

        active_student = user_factory(email="active_matrix@example.com", role=User.Role.STUDENT)
        pending_student = user_factory(email="pending_matrix@example.com", role=User.Role.STUDENT)
        revoked_student = user_factory(email="revoked_matrix@example.com", role=User.Role.STUDENT)
        non_enrolled_student = user_factory(
            email="non_enrolled_matrix@example.com", role=User.Role.STUDENT
        )

        course = Course.objects.create(
            title="Matrix Course", slug="matrix-course", is_published=True
        )
        Enrollment.objects.create(
            student=active_student, course=course, status=Enrollment.Status.ACTIVE
        )
        Enrollment.objects.create(
            student=pending_student, course=course, status=Enrollment.Status.PENDING
        )
        Enrollment.objects.create(
            student=revoked_student, course=course, status=Enrollment.Status.REVOKED
        )

        mat = CourseMaterial.objects.create(
            course=course, title="Matrix Section", is_published=True
        )

        view_only_item = MaterialItem.objects.create(
            material=mat,
            title="View Only PDF",
            item_type=MaterialItem.ItemType.FILE,
            file=SimpleUploadedFile(
                "view_only.pdf", b"%PDF-1.4 view only doc", content_type="application/pdf"
            ),
            download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY,
            is_published=True,
        )
        open_enrolled_item = MaterialItem.objects.create(
            material=mat,
            title="Open Enrolled PDF",
            item_type=MaterialItem.ItemType.FILE,
            file=SimpleUploadedFile(
                "open.pdf", b"%PDF-1.4 open enrolled doc", content_type="application/pdf"
            ),
            download_policy=MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
            is_published=True,
        )
        request_req_item = MaterialItem.objects.create(
            material=mat,
            title="Request Required PDF",
            item_type=MaterialItem.ItemType.FILE,
            file=SimpleUploadedFile(
                "req.pdf", b"%PDF-1.4 request required doc", content_type="application/pdf"
            ),
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            is_published=True,
        )
        # Even with an approved request, request_required files must NOT be previewed
        DownloadRequest.objects.create(
            student=active_student,
            material_item=request_req_item,
            status=DownloadRequest.Status.APPROVED,
            decided_at=timezone.now(),
        )

        # 1. Active student tests
        client.force_login(active_student)

        # 1a. view_only -> 200 without request
        url_vo = reverse(
            "learn:material_preview",
            kwargs={"course_slug": course.slug, "item_id": view_only_item.id},
        )
        resp_vo = client.get(url_vo)
        assert resp_vo.status_code == 200
        assert resp_vo.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp_vo.headers.get("Cache-Control") == "private, no-store"
        assert resp_vo.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in resp_vo.headers.get("Content-Security-Policy", "")

        # 1b. open_to_enrolled -> 200 without request
        url_open = reverse(
            "learn:material_preview",
            kwargs={"course_slug": course.slug, "item_id": open_enrolled_item.id},
        )
        resp_open = client.get(url_open)
        assert resp_open.status_code == 200
        assert resp_open.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp_open.headers.get("Cache-Control") == "private, no-store"

        # 1c. request_required -> 403 refused even with approved request
        url_req = reverse(
            "learn:material_preview",
            kwargs={"course_slug": course.slug, "item_id": request_req_item.id},
        )
        resp_req = client.get(url_req)
        assert resp_req.status_code == 403

        # 2. Pending student -> 403 refused
        client.force_login(pending_student)
        assert client.get(url_vo).status_code == 403
        assert client.get(url_open).status_code == 403

        # 3. Revoked student -> 403 refused
        client.force_login(revoked_student)
        assert client.get(url_vo).status_code == 403
        assert client.get(url_open).status_code == 403

        # 4. Non-enrolled student -> 403 refused
        client.force_login(non_enrolled_student)
        assert client.get(url_vo).status_code == 403
        assert client.get(url_open).status_code == 403

    def test_production_csp_settings_and_frame_src(self, client: Client, monkeypatch):
        """
        Loads the real production settings module config.settings.prod and asserts:
        - base-uri is 'self'
        - object-src is 'none'
        - frame-src includes youtube-nocookie, vimeo, bunny
        - frame-src contains NO global 'self'
        - emitted response header under production settings matches exactly
        """
        monkeypatch.setenv("SECRET_KEY", "a" * 64)
        monkeypatch.setenv("ALLOWED_HOSTS", "example.com,testserver")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///db.sqlite3")

        import importlib

        import config.settings.prod as prod_settings

        importlib.reload(prod_settings)

        prod_csp = prod_settings.CONTENT_SECURITY_POLICY
        prod_directives = prod_csp["DIRECTIVES"]

        assert prod_directives.get("base-uri") == ["'self'"]
        assert prod_directives.get("object-src") == ["'none'"]
        assert prod_directives.get("upgrade-insecure-requests") is True

        frame_src = prod_directives.get("frame-src", [])
        assert "https://www.youtube-nocookie.com" in frame_src
        assert "https://player.vimeo.com" in frame_src
        assert "https://iframe.mediadelivery.net" in frame_src
        assert "'self'" not in frame_src, "Production frame-src must not contain global 'self'"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                settings,
                "CONTENT_SECURITY_POLICY",
                prod_csp,
            )
            resp = client.get("/")
            assert resp.status_code == 200
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "base-uri 'self'" in csp
            assert "object-src 'none'" in csp
            assert "frame-src" in csp
            frame_part = csp.split("frame-src")[1].split(";")[0]
            assert "https://www.youtube-nocookie.com" in frame_part
            assert "https://player.vimeo.com" in frame_part
            assert "https://iframe.mediadelivery.net" in frame_part
            assert "'self'" not in frame_part, "frame-src header must not contain 'self'"

    def test_error_routes_return_404_under_production_urls(self, client: Client):
        """
        Under production URL configuration (ROOT_URLCONF='config.urls' with DEBUG=False),
        direct error preview routes /403/, /404/, /500/ must not be routable and return 404.
        """
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "ROOT_URLCONF", "config.urls")
            mp.setattr(settings, "DEBUG", False)
            resp_500 = client.get("/500/")
            assert resp_500.status_code == 404
            resp_403 = client.get("/403/")
            assert resp_403.status_code == 404
            resp_404 = client.get("/404/")
            assert resp_404.status_code == 404

    def test_material_preview_content_type_mapping(self, client: Client, user_factory):
        """
        Preview endpoint must set exact MIME types:
        - pdf -> application/pdf
        - jpg / jpeg -> image/jpeg
        - png -> image/png
        - webp -> image/webp
        - unknown extension (e.g. txt, docx) -> 403 PermissionDenied
        """
        student = user_factory(email="preview_mime_student@example.com", role=User.Role.STUDENT)
        course = Course.objects.create(title="MIME Course", slug="mime-course", is_published=True)
        Enrollment.objects.create(student=student, course=course, status=Enrollment.Status.ACTIVE)
        mat = CourseMaterial.objects.create(course=course, title="Docs", is_published=True)

        samples = [
            ("sample.pdf", b"%PDF-1.4 pdf data", "application/pdf", 200),
            ("sample.jpg", b"\xff\xd8\xff jpg data", "image/jpeg", 200),
            ("sample.jpeg", b"\xff\xd8\xff jpeg data", "image/jpeg", 200),
            ("sample.png", b"\x89PNG png data", "image/png", 200),
            ("sample.webp", b"RIFF....WEBP webp data", "image/webp", 200),
            ("notes.txt", b"plain text", "", 403),
            ("doc.docx", b"PK docx data", "", 403),
        ]

        client.force_login(student)
        for filename, content, expected_mime, expected_status in samples:
            item = MaterialItem.objects.create(
                material=mat,
                title=f"Item {filename}",
                item_type=MaterialItem.ItemType.FILE,
                file=SimpleUploadedFile(filename, content),
                download_policy=MaterialItem.DownloadPolicy.VIEW_ONLY
                if expected_status == 200
                else MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
                is_published=True,
            )
            url = reverse(
                "learn:material_preview", kwargs={"course_slug": course.slug, "item_id": item.id}
            )
            resp = client.get(url)
            assert resp.status_code == expected_status, (
                f"Expected {expected_status} for {filename}, got {resp.status_code}"
            )
            if expected_status == 200:
                assert resp.headers.get("Content-Type") == expected_mime, (
                    f"Expected {expected_mime} for {filename}, got {resp.headers.get('Content-Type')}"
                )


@pytest.mark.django_db
class TestCustom500Handler:
    """Verifies that 500.html inline styles are strictly permitted via SHA-256 hash."""

    def test_500_style_hash_computation_matches_template(self):
        """Calculated SHA-256 hash must exactly match the <style> content in 500.html."""
        template_path = Path(settings.BASE_DIR) / "templates" / "500.html"
        assert template_path.exists()
        content = template_path.read_text(encoding="utf-8")
        match = re.search(r"<style>(.*?)</style>", content, re.DOTALL)
        assert match is not None, "500.html must contain a <style> block"

        style_content = match.group(1)
        expected_digest = hashlib.sha256(style_content.encode("utf-8")).digest()
        expected_hash = base64.b64encode(expected_digest).decode("ascii")

        calculated_hash = get_500_style_hash()
        assert calculated_hash == expected_hash

    def test_500_response_includes_sha256_hash_in_style_src(self):
        """Custom handler500 must attach the style-src hash update to the response."""
        rf = RequestFactory()
        request = rf.get("/trigger-500/")
        resp = handler500(request)

        assert resp.status_code == 500
        style_hash = get_500_style_hash()
        expected_src = f"'sha256-{style_hash}'"

        # Check update attribute hook for django-csp
        assert hasattr(resp, "_csp_update")
        assert "style-src" in resp._csp_update
        assert expected_src in resp._csp_update["style-src"]


class TestCrossOriginResourcePolicy:
    """Tests Cross-Origin-Resource-Policy injection on downloads and exports."""

    def test_corp_header_on_attachment(self):
        middleware = SecurityHeadersMiddleware(
            lambda req: HttpResponse(
                b"data",
                headers={"Content-Disposition": 'attachment; filename="export.csv"'},
            )
        )
        rf = RequestFactory()
        resp = middleware(rf.get("/export/"))
        assert resp.headers.get("Cross-Origin-Resource-Policy") == "same-origin"

    def test_corp_header_on_fileresponse(self, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4...")
        middleware = SecurityHeadersMiddleware(lambda req: FileResponse(open(test_file, "rb")))
        rf = RequestFactory()
        resp = middleware(rf.get("/download/"))
        assert resp.headers.get("Cross-Origin-Resource-Policy") == "same-origin"

    def test_corp_header_not_on_regular_html(self):
        middleware = SecurityHeadersMiddleware(
            lambda req: HttpResponse("<html></html>", content_type="text/html")
        )
        rf = RequestFactory()
        resp = middleware(rf.get("/"))
        assert "Cross-Origin-Resource-Policy" not in resp.headers


@pytest.mark.django_db
class TestSessionIdleTimeout:
    """Tests session idle timeout expiration and activity refresh."""

    def test_session_expires_after_inactivity(self, user_factory):
        from importlib import import_module

        session_store = import_module(settings.SESSION_ENGINE).SessionStore()
        session_store["_last_activity"] = int(time.time()) - 1000

        user = user_factory(role=User.Role.STUDENT)
        rf = RequestFactory()
        request = rf.get("/learn/")
        request.user = user
        request.session = session_store

        # Override timeout to 300 seconds
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 300)
            middleware = SessionIdleTimeoutMiddleware(lambda req: HttpResponse("ok"))
            response = middleware(request)

            assert response.status_code == 302
            assert response.url in (reverse("account_login"), "/accounts/login/")

    def test_session_refreshed_on_active_request(self, user_factory):
        from importlib import import_module

        session_store = import_module(settings.SESSION_ENGINE).SessionStore()
        now_ts = int(time.time())
        session_store["_last_activity"] = now_ts - 50

        user = user_factory(role=User.Role.STUDENT)
        rf = RequestFactory()
        request = rf.get("/learn/progress/")
        request.user = user
        request.session = session_store

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 300)
            middleware = SessionIdleTimeoutMiddleware(lambda req: HttpResponse("ok"))
            response = middleware(request)

            assert response.status_code == 200
            assert request.session["_last_activity"] >= now_ts


class TestTemplateSecurityRegressions:
    """
    Static regression scanning of all templates to ensure zero inline script,
    zero on*= event handlers, zero javascript: URLs, and proper iframe attributes.
    """

    def test_zero_inline_executable_scripts_in_templates(self):
        """Assert zero inline <script> tags without non-executable type in templates."""
        template_dir = Path(settings.BASE_DIR) / "templates"
        violations = []

        script_tag_re = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)

        for path in template_dir.rglob("*.html"):
            content = path.read_text(encoding="utf-8")
            for match in script_tag_re.finditer(content):
                attrs = match.group(1)
                body = match.group(2).strip()

                # If it has a src attribute, it's external static JS (allowed)
                if "src=" in attrs:
                    continue
                # If it is JSON-LD or JSON data script, it's non-executable data (allowed)
                if 'type="application/ld+json"' in attrs or "type='application/ld+json'" in attrs:
                    continue
                if 'type="application/json"' in attrs or "type='application/json'" in attrs:
                    continue

                if body:
                    violations.append(
                        f"{path.relative_to(settings.BASE_DIR)}: inline script found: {body[:60]}..."
                    )

        assert not violations, "Found inline executable scripts in templates:\n" + "\n".join(
            violations
        )

    def test_zero_inline_event_handlers_in_templates(self):
        """Assert zero on* attributes (onclick, onchange, etc.) in non-email templates."""
        template_dir = Path(settings.BASE_DIR) / "templates"
        on_attr_re = re.compile(r"""\s(on[a-z]+)\s*=\s*['"]""", re.IGNORECASE)
        violations = []

        for path in template_dir.rglob("*.html"):
            # Exclude email templates
            rel_path = path.relative_to(template_dir).as_posix()
            if rel_path.startswith("emails/") or "/email/" in rel_path:
                continue

            content = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), start=1):
                match = on_attr_re.search(line)
                if match:
                    violations.append(
                        f"{path.relative_to(settings.BASE_DIR)}:L{line_no}: handler '{match.group(1)}' in: {line.strip()}"
                    )

        assert not violations, "Found inline on* event handlers in templates:\n" + "\n".join(
            violations
        )

    def test_zero_javascript_pseudo_urls_in_templates(self):
        """Assert zero javascript: URLs in templates."""
        template_dir = Path(settings.BASE_DIR) / "templates"
        js_url_re = re.compile(r"""(href|action)\s*=\s*['"]\s*javascript:""", re.IGNORECASE)
        violations = []

        for path in template_dir.rglob("*.html"):
            content = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if js_url_re.search(line):
                    violations.append(
                        f"{path.relative_to(settings.BASE_DIR)}:L{line_no}: javascript: URL in: {line.strip()}"
                    )

        assert not violations, "Found javascript: URLs in templates:\n" + "\n".join(violations)

    def test_zero_inline_style_attributes_in_web_templates(self):
        """Assert zero inline style="..." attributes outside email templates."""
        template_dir = Path(settings.BASE_DIR) / "templates"
        style_attr_re = re.compile(r"""\sstyle\s*=\s*['"]""", re.IGNORECASE)
        violations = []

        for path in template_dir.rglob("*.html"):
            rel_path = path.relative_to(template_dir).as_posix()
            # Email templates require inline styles for client rendering
            if rel_path.startswith("emails/") or "/email/" in rel_path:
                continue

            content = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if style_attr_re.search(line):
                    violations.append(
                        f"{path.relative_to(settings.BASE_DIR)}:L{line_no}: inline style in: {line.strip()}"
                    )

        assert not violations, "Found inline style attributes in web templates:\n" + "\n".join(
            violations
        )

    def test_video_iframes_have_referrerpolicy_and_sandbox(self):
        """Assert all video iframes declare strict-origin-when-cross-origin and sandbox."""
        template_dir = Path(settings.BASE_DIR) / "templates"
        iframe_tag_re = re.compile(r"<iframe\b([^>]*)>", re.DOTALL | re.IGNORECASE)

        for path in template_dir.rglob("*.html"):
            content = path.read_text(encoding="utf-8")
            for match in iframe_tag_re.finditer(content):
                attrs = match.group(1)
                assert (
                    'referrerpolicy="strict-origin-when-cross-origin"' in attrs
                    or "referrerpolicy='strict-origin-when-cross-origin'" in attrs
                ), f"{path}: iframe missing referrerpolicy='strict-origin-when-cross-origin'"
                assert "sandbox=" in attrs, f"{path}: iframe missing sandbox attribute"
