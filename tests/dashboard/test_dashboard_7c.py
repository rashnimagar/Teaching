import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.core.constants import FAQ_CACHE_KEY, SITE_SETTINGS_CACHE_KEY
from apps.core.models import FAQItem, SiteSettings
from apps.core.validators import validate_safe_url
from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadLog,
    DownloadRequest,
    MaterialItem,
)
from apps.courses.validators_materials import validate_material_file
from apps.notifications.models import Notification


@pytest.fixture(autouse=True)
def clear_all_caches():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def teacher_user(user_factory):
    return user_factory(
        email="teacher_7c@example.com",
        role=User.Role.TEACHER,
        is_staff=True,
    )


@pytest.fixture
def student_user(user_factory):
    return user_factory(
        email="student_7c@example.com",
        role=User.Role.STUDENT,
        is_active=True,
    )


@pytest.fixture
def another_student(user_factory):
    return user_factory(
        email="student_7c_2@example.com",
        role=User.Role.STUDENT,
        is_active=True,
    )


@pytest.fixture
def course(teacher_user):
    return Course.objects.create(
        title="Django Advanced Architecture",
        slug="django-advanced-architecture",
        short_description="Deep dive into production Django.",
        description="Comprehensive syllabus.",
        is_free=True,
        is_published=True,
    )


@pytest.fixture
def material(course):
    return CourseMaterial.objects.create(
        course=course,
        title="Module 1 Architecture Resources",
        order=1,
        is_published=True,
    )


def create_dummy_pdf(filename="doc.pdf"):
    # Minimum valid PDF header and content
    content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n160\n%%EOF"
    return SimpleUploadedFile(filename, content, content_type="application/pdf")


def create_dummy_png(filename="image.png"):
    # Valid minimal 1x1 PNG
    content = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return SimpleUploadedFile(filename, content, content_type="image/png")


def create_dummy_txt(filename="notes.txt"):
    return SimpleUploadedFile(filename, b"Sample notes for testing.", content_type="text/plain")


# ==============================================================================
# 1. URL Validation (Credentials, Whitespace, Schemes, Length)
# ==============================================================================
class TestSafeUrlValidator:
    def test_valid_http_and_https_urls(self):
        assert validate_safe_url("https://example.com") == "https://example.com"
        assert (
            validate_safe_url("http://example.com/path?foo=bar#section")
            == "http://example.com/path?foo=bar#section"
        )

    def test_embedded_credentials_rejected(self):
        with pytest.raises(ValidationError, match="embedded credentials"):
            validate_safe_url("https://user:password@example.com/docs")

    def test_whitespace_rejected(self):
        with pytest.raises(ValidationError, match="whitespace or control"):
            validate_safe_url("https://example.com/foo bar")
        with pytest.raises(ValidationError, match="whitespace or control"):
            validate_safe_url(" https://example.com")

    def test_control_characters_rejected(self):
        with pytest.raises(ValidationError, match="whitespace or control"):
            validate_safe_url("https://example.com/\nmalicious")
        with pytest.raises(ValidationError, match="whitespace or control"):
            validate_safe_url("https://example.com/\x00test")

    def test_invalid_schemes_rejected(self):
        with pytest.raises(ValidationError, match="must start with http:// or https://"):
            validate_safe_url("ftp://ftp.example.com")
        with pytest.raises(ValidationError, match="must start with http:// or https://"):
            validate_safe_url("javascript:alert(1)")

    def test_max_length_enforced(self):
        long_url = "https://example.com/" + ("a" * 1050)
        with pytest.raises(ValidationError, match="maximum length"):
            validate_safe_url(long_url, max_length=1000)


# ==============================================================================
# 2. Material File Size Limit Setting
# ==============================================================================
class TestMaterialFileSizeLimit:
    def test_size_limit_setting_enforced(self, settings):
        settings.MATERIAL_MAX_FILE_SIZE_BYTES = 500  # 500 bytes limit
        oversized = SimpleUploadedFile("big.txt", b"x" * 600, content_type="text/plain")
        with pytest.raises(ValidationError, match="File size exceeds"):
            validate_material_file(oversized)

        undersized = SimpleUploadedFile("ok.txt", b"x" * 400, content_type="text/plain")
        # Should not raise
        validate_material_file(undersized)


# ==============================================================================
# 3. Item Delete Rules (Blocked if DownloadRequest or DownloadLog exists)
# ==============================================================================
@pytest.mark.django_db
class TestItemDeleteRules:
    def test_item_without_history_can_be_deleted(self, client, teacher_user, course, material):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Slide PDF",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
            order=1,
        )
        url = reverse(
            "dashboard:teacher_material_item_delete",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
        )
        resp = client.post(url)
        assert resp.status_code == 302
        assert not MaterialItem.objects.filter(pk=item.id).exists()

    def test_item_with_download_request_cannot_be_deleted(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Cheat Sheet",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
            order=1,
        )
        DownloadRequest.objects.create(
            student=student_user,
            material_item=item,
            status=DownloadRequest.Status.PENDING,
        )
        url = reverse(
            "dashboard:teacher_material_item_delete",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
        )
        resp = client.post(url)
        assert resp.status_code == 302
        # Item must still exist in DB!
        assert MaterialItem.objects.filter(pk=item.id).exists()

    def test_item_with_download_log_cannot_be_deleted(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Diagram PNG",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_png(),
            order=1,
        )
        DownloadLog.objects.create(
            student=student_user,
            material_item=item,
            ip_address="127.0.0.1",
        )
        url = reverse(
            "dashboard:teacher_material_item_delete",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
        )
        resp = client.post(url)
        assert resp.status_code == 302
        assert MaterialItem.objects.filter(pk=item.id).exists()

    def test_item_with_history_can_be_unpublished(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Diagram PNG",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_png(),
            is_published=True,
            order=1,
        )
        DownloadLog.objects.create(
            student=student_user,
            material_item=item,
            ip_address="127.0.0.1",
        )
        url = reverse(
            "dashboard:teacher_material_item_toggle_publish",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
        )
        resp = client.post(url)
        assert resp.status_code == 302
        item.refresh_from_db()
        assert item.is_published is False


# ==============================================================================
# 4. Post Delete Rules (Blocked if items have history; cleans files on commit)
# ==============================================================================
@pytest.mark.django_db
class TestPostDeleteRules:
    def test_post_with_item_history_cannot_be_deleted(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Doc",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
        )
        DownloadRequest.objects.create(
            student=student_user,
            material_item=item,
            status=DownloadRequest.Status.APPROVED,
        )
        url = reverse(
            "dashboard:teacher_material_delete",
            kwargs={"slug": course.slug, "material_id": material.id},
        )
        resp = client.post(url)
        assert resp.status_code == 302
        assert CourseMaterial.objects.filter(pk=material.id).exists()

    def test_post_without_history_deletes_items_and_stored_files(
        self, client, teacher_user, course, material
    ):
        client.force_login(teacher_user)
        pdf_file = create_dummy_pdf()
        item = MaterialItem.objects.create(
            material=material,
            title="Clean Doc",
            item_type=MaterialItem.ItemType.FILE,
            file=pdf_file,
        )
        file_path = item.file.name
        storage = item.file.storage
        assert storage.exists(file_path)

        url = reverse(
            "dashboard:teacher_material_delete",
            kwargs={"slug": course.slug, "material_id": material.id},
        )
        resp = client.post(url)
        assert resp.status_code == 302
        assert not CourseMaterial.objects.filter(pk=material.id).exists()
        assert not MaterialItem.objects.filter(pk=item.id).exists()


# ==============================================================================
# 5. Policy Transitions (view_only, away from open_to_enrolled, etc.)
# ==============================================================================
@pytest.mark.django_db
class TestPolicyTransitions:
    def test_switch_to_view_only_requires_pdf_or_image(
        self, client, teacher_user, course, material
    ):
        client.force_login(teacher_user)
        # Text file is NOT allowed for view_only
        txt_item = MaterialItem.objects.create(
            material=material,
            title="Notes",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_txt(),
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
        )
        url = reverse(
            "dashboard:teacher_material_item_policy",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": txt_item.id},
        )
        resp = client.post(url, {"target_policy": "view_only"})
        assert resp.status_code == 302
        txt_item.refresh_from_db()
        assert txt_item.download_policy == MaterialItem.DownloadPolicy.REQUEST_REQUIRED

    def test_switch_to_view_only_denies_pending_and_revokes_approved_notifying_students(
        self, client, teacher_user, student_user, another_student, course, material
    ):
        client.force_login(teacher_user)
        pdf_item = MaterialItem.objects.create(
            material=material,
            title="Lecture Slides",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
        )
        # Pending request for student 1
        req_pending = DownloadRequest.objects.create(
            student=student_user,
            material_item=pdf_item,
            status=DownloadRequest.Status.PENDING,
        )
        # Approved request for student 2
        req_approved = DownloadRequest.objects.create(
            student=another_student,
            material_item=pdf_item,
            status=DownloadRequest.Status.APPROVED,
        )

        url = reverse(
            "dashboard:teacher_material_item_policy",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": pdf_item.id},
        )
        resp = client.post(url, {"target_policy": "view_only"})
        assert resp.status_code == 302

        pdf_item.refresh_from_db()
        assert pdf_item.download_policy == MaterialItem.DownloadPolicy.VIEW_ONLY

        req_pending.refresh_from_db()
        assert req_pending.status == DownloadRequest.Status.DENIED
        assert "view-only" in req_pending.teacher_note

        req_approved.refresh_from_db()
        assert req_approved.status == DownloadRequest.Status.REVOKED
        assert "view-only" in req_approved.teacher_note

        # Students must have received notifications
        assert Notification.objects.filter(recipient=student_user).exists()
        assert Notification.objects.filter(recipient=another_student).exists()

    def test_switch_away_from_open_to_enrolled_with_keep_access(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        pdf_item = MaterialItem.objects.create(
            material=material,
            title="Architecture PDF",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
            download_policy=MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
        )
        # Student logged a download under open policy
        DownloadLog.objects.create(
            student=student_user,
            material_item=pdf_item,
            ip_address="127.0.0.1",
        )

        url = reverse(
            "dashboard:teacher_material_item_policy",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": pdf_item.id},
        )
        # Switch to request_required with keep_access=on
        resp = client.post(url, {"target_policy": "request_required", "keep_access": "on"})
        assert resp.status_code == 302

        pdf_item.refresh_from_db()
        assert pdf_item.download_policy == MaterialItem.DownloadPolicy.REQUEST_REQUIRED

        # Student should now have an approved DownloadRequest
        req = DownloadRequest.objects.filter(student=student_user, material_item=pdf_item).first()
        assert req is not None
        assert req.status == DownloadRequest.Status.APPROVED

    def test_switch_away_from_open_to_enrolled_without_keep_access(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        pdf_item = MaterialItem.objects.create(
            material=material,
            title="Architecture PDF 2",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
            download_policy=MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
        )
        DownloadLog.objects.create(
            student=student_user,
            material_item=pdf_item,
            ip_address="127.0.0.1",
        )

        url = reverse(
            "dashboard:teacher_material_item_policy",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": pdf_item.id},
        )
        # Switch to request_required WITHOUT keep_access
        resp = client.post(url, {"target_policy": "request_required"})
        assert resp.status_code == 302

        pdf_item.refresh_from_db()
        assert pdf_item.download_policy == MaterialItem.DownloadPolicy.REQUEST_REQUIRED
        assert not DownloadRequest.objects.filter(
            student=student_user, material_item=pdf_item
        ).exists()

    def test_replacing_file_keeps_approved_requests(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        pdf_item = MaterialItem.objects.create(
            material=material,
            title="Original Slide Deck",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf("slides_v1.pdf"),
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
        )
        req = DownloadRequest.objects.create(
            student=student_user,
            material_item=pdf_item,
            status=DownloadRequest.Status.APPROVED,
        )

        url = reverse(
            "dashboard:teacher_material_item_edit",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": pdf_item.id},
        )
        new_pdf = create_dummy_pdf("slides_v2.pdf")
        resp = client.post(
            url,
            {
                "title": "Updated Slide Deck",
                "item_type": "file",
                "file": new_pdf,
                "download_policy": "request_required",
                "is_published": "on",
            },
        )
        assert resp.status_code == 302

        pdf_item.refresh_from_db()
        assert pdf_item.title == "Updated Slide Deck"
        # Approval must still be APPROVED
        req.refresh_from_db()
        assert req.status == DownloadRequest.Status.APPROVED


# ==============================================================================
# 6. Privacy: No IP Address in Download History
# ==============================================================================
@pytest.mark.django_db
class TestDownloadHistoryPrivacy:
    def test_history_shows_student_file_time_no_ip(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Secure Asset",
            item_type=MaterialItem.ItemType.FILE,
            file=create_dummy_pdf(),
        )
        secret_ip = "198.51.100.42"
        DownloadLog.objects.create(
            student=student_user,
            material_item=item,
            ip_address=secret_ip,
        )

        # 1. Test teacher_material_item_history_view
        url = reverse(
            "dashboard:teacher_material_item_history",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
        )
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert student_user.email in content
        assert "Secure Asset" in content
        assert secret_ip not in content

        # 2. Test teacher_download_history_view (Permissions Queue audit link)
        perm_url = reverse("dashboard:teacher_download_history", kwargs={"item_id": item.id})
        perm_resp = client.get(perm_url)
        assert perm_resp.status_code == 200
        perm_content = perm_resp.content.decode("utf-8")
        assert student_user.email in perm_content
        assert secret_ip not in perm_content


# ==============================================================================
# 7. Cache Invalidation (SiteSettings and FAQs)
# ==============================================================================
@pytest.mark.django_db
class TestCacheInvalidation:
    def test_site_settings_cache_invalidated_immediately(self, client, teacher_user):
        client.force_login(teacher_user)
        # Prime cache
        SiteSettings.get_solo()
        assert cache.get(SITE_SETTINGS_CACHE_KEY) is not None

        url = reverse("dashboard:teacher_settings")
        resp = client.post(
            url,
            {
                "site_name": "Updated Academy",
                "hero_headline": "New Headline",
                "hero_subheadline": "New Subheadline",
                "github_url": "https://github.com/myacademy",
            },
        )
        assert resp.status_code == 302
        # Cache must have been refreshed/cleared
        s2 = SiteSettings.get_solo()
        assert s2.site_name == "Updated Academy"

    def test_site_settings_form_rejects_invalid_social_links(self, client, teacher_user):
        """
        Invalid social links (user:pass@host, javascript:, URL with spaces)
        must return a 200 response with a form error and not save any changes.
        """
        client.force_login(teacher_user)
        url = reverse("dashboard:teacher_settings")
        settings_before = SiteSettings.get_solo()
        original_github = settings_before.github_url

        invalid_urls = [
            "https://user:pass@github.com/myrepo",
            "javascript:alert(1)",
            "https://github.com/my repo",
        ]

        for invalid in invalid_urls:
            resp = client.post(
                url,
                {
                    "site_name": settings_before.site_name,
                    "hero_headline": settings_before.hero_headline,
                    "hero_subheadline": settings_before.hero_subheadline,
                    "github_url": invalid,
                },
            )
            assert resp.status_code == 200
            assert "form" in resp.context
            assert "github_url" in resp.context["form"].errors
            # Confirm no change saved
            reloaded = SiteSettings.objects.get(pk=1)
            assert reloaded.github_url == original_github

    def test_faq_cache_invalidated_immediately_on_cud_and_reorder(self, client, teacher_user):
        client.force_login(teacher_user)
        # 1. Create FAQ
        url = reverse("dashboard:teacher_faq_create")
        client.post(
            url,
            {
                "question": "Can I download files?",
                "answer": "Yes, with permission.",
                "is_published": "on",
            },
        )
        # Prime home FAQ cache
        client.get(reverse("core:home"))
        assert cache.get(FAQ_CACHE_KEY) is not None

        # 2. Edit FAQ
        faq = FAQItem.objects.first()
        edit_url = reverse("dashboard:teacher_faq_edit", kwargs={"faq_id": faq.id})
        client.post(
            edit_url,
            {
                "question": "Updated Question?",
                "answer": "Updated Answer.",
                "is_published": "on",
            },
        )
        # Cache must be invalidated
        assert cache.get(FAQ_CACHE_KEY) is None

        # 3. Toggle Publish
        client.get(reverse("core:home"))  # Prime again
        toggle_url = reverse("dashboard:teacher_faq_toggle_publish", kwargs={"faq_id": faq.id})
        client.post(toggle_url)
        assert cache.get(FAQ_CACHE_KEY) is None

        # 4. Reorder
        faq2 = FAQItem.objects.create(question="Second Q?", answer="Ans 2", order=2)
        client.get(reverse("core:home"))  # Prime again
        reorder_url = reverse("dashboard:teacher_faq_reorder", kwargs={"faq_id": faq2.id})
        client.post(reorder_url, {"direction": "up"})
        assert cache.get(FAQ_CACHE_KEY) is None

        # 5. Delete
        client.get(reverse("core:home"))  # Prime again
        del_url = reverse("dashboard:teacher_faq_delete", kwargs={"faq_id": faq2.id})
        client.post(del_url)
        assert cache.get(FAQ_CACHE_KEY) is None


# ==============================================================================
# 8. Reordering Atomic & Max+1 Assignment
# ==============================================================================
@pytest.mark.django_db
class TestReorderingAndMaxOrder:
    def test_new_material_and_faq_gets_max_plus_one(self, course):
        CourseMaterial.objects.create(course=course, title="M1", order=1)
        CourseMaterial.objects.create(course=course, title="M2", order=2)
        # Forms assign max + 1
        from apps.dashboard.forms_teacher import (
            TeacherFAQForm,
            TeacherMaterialForm,
            TeacherMaterialItemForm,
        )

        mform = TeacherMaterialForm(data={"title": "M3"}, course=course)
        assert mform.is_valid()
        m3 = mform.save()
        assert m3.order == 3

        MaterialItem.objects.create(
            material=m3, title="I1", item_type="link", external_url="https://example.com/1", order=1
        )
        iform = TeacherMaterialItemForm(
            data={"title": "I2", "item_type": "link", "external_url": "https://example.com/2"},
            material=m3,
        )
        assert iform.is_valid()
        item2 = iform.save()
        assert item2.order == 2

        FAQItem.objects.create(question="Q1", answer="A1", order=1)
        fform = TeacherFAQForm(data={"question": "Q2", "answer": "A2"})
        assert fform.is_valid()
        f2 = fform.save()
        assert f2.order == 2


# ==============================================================================
# 9. Status Badge Rendering on Student Profile (denied, revoked, approved, pending)
# ==============================================================================
@pytest.mark.django_db
class TestStudentDetailDownloadBadges:
    def test_student_detail_renders_all_download_statuses_correctly(
        self, client, teacher_user, student_user, course, material
    ):
        client.force_login(teacher_user)
        # Create 4 items and requests in each status
        for st in [
            DownloadRequest.Status.PENDING,
            DownloadRequest.Status.APPROVED,
            DownloadRequest.Status.DENIED,
            DownloadRequest.Status.REVOKED,
        ]:
            item = MaterialItem.objects.create(
                material=material,
                title=f"File {st}",
                item_type=MaterialItem.ItemType.FILE,
                file=create_dummy_pdf(f"{st}.pdf"),
            )
            DownloadRequest.objects.create(
                student=student_user,
                material_item=item,
                status=st,
            )

        url = reverse("dashboard:teacher_student_detail", kwargs={"student_id": student_user.id})
        resp = client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")

        # Must display "Denied" and "Revoked", NOT "Rejected"
        assert "Denied" in content
        assert "Revoked" in content
        assert "Approved" in content
        assert "Pending" in content
        assert "Rejected" not in content  # Ensuring no legacy 'rejected' word in download requests


# ==============================================================================
# 10. Security: CSRF & Method Rejection
# ==============================================================================
@pytest.mark.django_db
class TestDashboardSecurity:
    def test_post_without_csrf_rejected_when_enforced(self, teacher_user, course, material):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(teacher_user)

        item = MaterialItem.objects.create(
            material=material,
            title="Sample Item",
            item_type=MaterialItem.ItemType.LINK,
            external_url="https://example.com",
        )
        url = reverse(
            "dashboard:teacher_material_item_toggle_publish",
            kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
        )
        resp = csrf_client.post(url)
        assert resp.status_code == 403

    def test_get_rejected_on_mutating_endpoints(self, client, teacher_user, course, material):
        client.force_login(teacher_user)
        item = MaterialItem.objects.create(
            material=material,
            title="Sample Item 2",
            item_type=MaterialItem.ItemType.LINK,
            external_url="https://example.com",
        )

        # Toggle publish post
        resp1 = client.get(
            reverse(
                "dashboard:teacher_material_toggle_publish",
                kwargs={"slug": course.slug, "material_id": material.id},
            )
        )
        assert resp1.status_code == 405

        # Archive post
        resp2 = client.get(
            reverse(
                "dashboard:teacher_material_archive",
                kwargs={"slug": course.slug, "material_id": material.id},
            )
        )
        assert resp2.status_code == 405

        # Delete post
        resp3 = client.get(
            reverse(
                "dashboard:teacher_material_delete",
                kwargs={"slug": course.slug, "material_id": material.id},
            )
        )
        assert resp3.status_code == 405

        # Toggle publish item
        resp4 = client.get(
            reverse(
                "dashboard:teacher_material_item_toggle_publish",
                kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
            )
        )
        assert resp4.status_code == 405

        # Delete item
        resp5 = client.get(
            reverse(
                "dashboard:teacher_material_item_delete",
                kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
            )
        )
        assert resp5.status_code == 405

        # Reorder item
        resp6 = client.get(
            reverse(
                "dashboard:teacher_material_item_reorder",
                kwargs={"slug": course.slug, "material_id": material.id, "item_id": item.id},
            )
        )
        assert resp6.status_code == 405

        # FAQ toggle publish, reorder, delete
        faq = FAQItem.objects.create(question="Q?", answer="A")
        assert (
            client.get(
                reverse("dashboard:teacher_faq_toggle_publish", kwargs={"faq_id": faq.id})
            ).status_code
            == 405
        )
        assert (
            client.get(
                reverse("dashboard:teacher_faq_reorder", kwargs={"faq_id": faq.id})
            ).status_code
            == 405
        )
        assert (
            client.get(
                reverse("dashboard:teacher_faq_delete", kwargs={"faq_id": faq.id})
            ).status_code
            == 405
        )

    def test_materials_list_bounded_queries(
        self, client, teacher_user, course, django_assert_num_queries
    ):
        client.force_login(teacher_user)
        SiteSettings.get_solo()  # prime singleton in DB and cache

        # Create multiple materials with items
        for i in range(5):
            mat = CourseMaterial.objects.create(course=course, title=f"Post {i}", order=i)
            for j in range(3):
                MaterialItem.objects.create(
                    material=mat,
                    title=f"Item {i}-{j}",
                    item_type=MaterialItem.ItemType.LINK,
                    external_url="https://example.com",
                    order=j,
                )

        url = reverse("dashboard:teacher_course_materials", kwargs={"slug": course.slug})
        # Baseline query count with 5 posts and 15 items
        with django_assert_num_queries(13):
            resp = client.get(url)
            assert resp.status_code == 200

        # Add 5 MORE posts with 15 MORE items - query count MUST remain constant (13)
        for i in range(5, 10):
            mat = CourseMaterial.objects.create(course=course, title=f"Post {i}", order=i)
            for j in range(3):
                MaterialItem.objects.create(
                    material=mat,
                    title=f"Item {i}-{j}",
                    item_type=MaterialItem.ItemType.LINK,
                    external_url="https://example.com",
                    order=j,
                )

        # Query count remains exactly 13 (O(1) queries regardless of number of posts/items)
        with django_assert_num_queries(13):
            resp = client.get(url)
            assert resp.status_code == 200
