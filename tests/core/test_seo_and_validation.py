import io

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.core.validators import validate_image_file
from apps.courses.models import Course

User = get_user_model()


@pytest.fixture
def test_teacher(user_factory):
    return user_factory(email="teacher.seo@example.com", role=User.Role.TEACHER, is_staff=True)


@pytest.fixture
def test_student(user_factory):
    return user_factory(email="student.seo@example.com", role=User.Role.STUDENT)


@pytest.mark.django_db
class TestSEOAndRobots:
    def test_robots_txt_contains_disallow_rules_and_sitemap(self, client: Client):
        resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/plain")
        content = resp.content.decode("utf-8")

        assert "Disallow: /admin/" in content
        assert "Disallow: /dashboard/" in content
        assert "Disallow: /accounts/" in content
        assert f"Sitemap: {settings.SITE_URL}/sitemap.xml" in content

    def test_sitemap_xml_uses_site_url_and_lists_published_courses(self, client: Client):
        c_pub = Course.objects.create(
            title="Sitemap Public Course",
            slug="sitemap-public-course",
            is_published=True,
            is_free=True,
        )
        c_unpub = Course.objects.create(
            title="Sitemap Hidden Course",
            slug="sitemap-hidden-course",
            is_published=False,
            is_free=True,
        )

        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert "xml" in resp["Content-Type"]
        content = resp.content.decode("utf-8")

        # Must use configured SITE_URL domain
        assert settings.SITE_URL in content
        assert f"/courses/{c_pub.slug}/" in content
        assert f"/courses/{c_unpub.slug}/" not in content

    def test_dashboards_include_noindex_meta_tag(self, client: Client, test_student, test_teacher):
        # Student dashboard
        client.force_login(test_student)
        s_resp = client.get(reverse("dashboard:student"))
        assert s_resp.status_code == 200
        assert '<meta name="robots" content="noindex, nofollow">' in s_resp.content.decode("utf-8")

        # Teacher dashboard
        client.force_login(test_teacher)
        t_resp = client.get(reverse("dashboard:teacher"))
        assert t_resp.status_code == 200
        assert '<meta name="robots" content="noindex, nofollow">' in t_resp.content.decode("utf-8")

    def test_canonical_and_og_tags_use_site_url(self, client: Client):
        img_io = io.BytesIO()
        img = Image.new("RGB", (400, 300), color="green")
        img.save(img_io, format="JPEG")
        img_io.seek(0)
        uploaded = SimpleUploadedFile("thumb.jpg", img_io.getvalue(), content_type="image/jpeg")

        course = Course.objects.create(
            title="SEO Canonical Course",
            slug="seo-canonical-course",
            thumbnail=uploaded,
            is_published=True,
            is_free=True,
        )

        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")

        expected_canonical = (
            f'<link rel="canonical" href="{settings.SITE_URL}/courses/{course.slug}/">'
        )
        expected_og_url = (
            f'<meta property="og:url" content="{settings.SITE_URL}/courses/{course.slug}/">'
        )
        assert expected_canonical in content
        assert expected_og_url in content
        assert (
            f'<meta property="og:image" content="{settings.SITE_URL}{course.thumbnail.url}">'
            in content
        )

    def test_favicon_and_font_preloads_in_base_template(self, client: Client):
        resp = client.get("/")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")

        # Font preloads
        assert (
            'rel="preload" href="/static/fonts/inter-variable-latin.woff2" as="font" type="font/woff2"'
            in content
        )
        assert (
            'rel="preload" href="/static/fonts/plus-jakarta-sans-variable-latin.woff2" as="font" type="font/woff2"'
            in content
        )

        # Favicon links
        assert 'rel="icon" type="image/svg+xml" href="/static/favicon.svg"' in content
        assert 'rel="alternate icon" href="/static/favicon.ico"' in content

    def test_favicon_ico_route_redirects_to_static_file(self, client: Client):
        resp = client.get("/favicon.ico")
        assert resp.status_code in (301, 302)
        assert "/static/favicon.ico" in resp.url


@pytest.mark.django_db
class TestImageUploadValidation:
    def test_valid_image_passes_validation_and_generates_webp(self):
        # Create an in-memory test image
        img_io = io.BytesIO()
        img = Image.new("RGB", (800, 600), color="blue")
        img.save(img_io, format="JPEG")
        img_io.seek(0)

        uploaded = SimpleUploadedFile(
            "test_thumbnail.jpg", img_io.getvalue(), content_type="image/jpeg"
        )

        # Validator should pass without error
        validate_image_file(uploaded)

        # Saving to Course model should generate WebP variant
        course = Course.objects.create(
            title="Image Variant Course",
            slug="image-variant-course",
            thumbnail=uploaded,
            is_published=True,
            is_free=True,
        )
        assert course.thumbnail.name != ""
        assert course.thumbnail_webp.name != ""
        assert course.thumbnail_webp.name.endswith(".webp")

    def test_corrupted_or_non_image_file_rejected(self):
        # Text file pretending to be jpg
        fake_img = SimpleUploadedFile(
            "fake.jpg", b"This is plain text not an image", content_type="image/jpeg"
        )
        with pytest.raises(ValidationError) as exc:
            validate_image_file(fake_img)
        assert "not a valid or supported image" in str(exc.value)

    def test_image_exceeding_max_size_rejected(self):
        # File > 5 MB
        oversized_data = b"0" * (5 * 1024 * 1024 + 1024)
        oversized_file = SimpleUploadedFile("large.png", oversized_data, content_type="image/png")
        with pytest.raises(ValidationError) as exc:
            validate_image_file(oversized_file)
        assert "exceeds 5 MB limit" in str(exc.value)

    def test_unsupported_image_extension_rejected(self):
        img_io = io.BytesIO()
        img = Image.new("RGB", (100, 100), color="red")
        img.save(img_io, format="GIF")
        img_io.seek(0)

        gif_file = SimpleUploadedFile("anim.gif", img_io.getvalue(), content_type="image/gif")
        with pytest.raises(ValidationError) as exc:
            validate_image_file(gif_file)
        assert "not supported" in str(exc.value)
