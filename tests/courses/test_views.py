from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models import SiteSettings
from apps.courses.models import Course, Lesson


@pytest.fixture
def sample_courses(db):
    """Creates a diverse set of courses for testing catalog, search, and visibility."""
    c_published_free = Course.objects.create(
        title="Intro to Python Fundamentals",
        slug="intro-to-python",
        short_description="Learn core Python programming concepts from scratch.",
        description="Full course covering data structures and control flow.",
        is_published=True,
        is_featured=True,
        is_free=True,
    )
    c_published_paid = Course.objects.create(
        title="Advanced Web Development with Django",
        slug="advanced-django",
        short_description="Build production web apps with Django 5.2.",
        description="Comprehensive masterclass on modern backend architecture.",
        is_published=True,
        is_featured=False,
        is_free=False,
        price=Decimal("4999.00"),
        currency="NPR",
    )
    c_unpublished = Course.objects.create(
        title="Draft Unpublished Course",
        slug="draft-course",
        short_description="This course should never be visible to the public.",
        is_published=False,
        is_free=True,
    )
    c_archived = Course.objects.create(
        title="Archived Legacy Course",
        slug="archived-course",
        short_description="This course is archived and closed.",
        is_published=True,
        is_archived=True,
        is_free=True,
    )

    # Add lessons to the published free course
    Lesson.objects.create(
        course=c_published_free,
        title="1. Introduction Video",
        order=1,
        video_provider=Lesson.VideoProvider.YOUTUBE,
        video_id="dQw4w9WgXcQ",
        is_preview=True,
        is_published=True,
    )
    Lesson.objects.create(
        course=c_published_free,
        title="2. Secret Advanced Lesson",
        order=2,
        video_provider=Lesson.VideoProvider.BUNNY,
        video_id="bunny-secret-video-guid-99999",
        is_preview=False,
        is_published=True,
    )
    Lesson.objects.create(
        course=c_published_free,
        title="3. Unpublished Draft Lesson",
        order=3,
        video_provider=Lesson.VideoProvider.YOUTUBE,
        video_id="abcdefghijk",
        is_preview=False,
        is_published=False,
    )

    return {
        "free": c_published_free,
        "paid": c_published_paid,
        "unpublished": c_unpublished,
        "archived": c_archived,
    }


@pytest.mark.django_db
class TestCourseVisibilityAndCatalog:
    def test_catalog_shows_only_published_non_archived_courses(
        self, client: Client, sample_courses
    ):
        url = reverse("courses:list")
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        assert "Intro to Python Fundamentals" in content
        assert "Advanced Web Development with Django" in content
        assert "Draft Unpublished Course" not in content
        assert "Archived Legacy Course" not in content

    def test_course_detail_404_for_unpublished_and_archived(self, client: Client, sample_courses):
        # Published free course returns 200
        resp = client.get(reverse("courses:detail", kwargs={"slug": sample_courses["free"].slug}))
        assert resp.status_code == 200

        # Unpublished course returns 404
        resp = client.get(
            reverse("courses:detail", kwargs={"slug": sample_courses["unpublished"].slug})
        )
        assert resp.status_code == 404

        # Archived course returns 404
        resp = client.get(
            reverse("courses:detail", kwargs={"slug": sample_courses["archived"].slug})
        )
        assert resp.status_code == 404

    def test_course_search_by_keyword(self, client: Client, sample_courses):
        url = reverse("courses:list")

        # Search for "Python"
        resp = client.get(f"{url}?q=Python")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Intro to Python Fundamentals" in content
        assert "Advanced Web Development" not in content

        # Search for "Django"
        resp = client.get(f"{url}?q=Django")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Advanced Web Development with Django" in content
        assert "Intro to Python" not in content

    def test_course_filter_by_type(self, client: Client, sample_courses):
        url = reverse("courses:list")

        # Filter: free
        resp = client.get(f"{url}?filter=free")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Intro to Python Fundamentals" in content
        assert "Advanced Web Development with Django" not in content

        # Filter: paid
        resp = client.get(f"{url}?filter=paid")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Advanced Web Development with Django" in content
        assert "Intro to Python Fundamentals" not in content

        # Invalid filter parameter defaults gracefully to all
        resp = client.get(f"{url}?filter=invalid_random_filter")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Intro to Python Fundamentals" in content
        assert "Advanced Web Development with Django" in content


@pytest.mark.django_db
class TestLessonSecurityAndDataIntegrity:
    def test_non_preview_video_id_is_never_in_html(self, client: Client, sample_courses):
        """
        Verify security requirement: Video IDs and provider info for non-preview
        lessons must NEVER be leaked in the HTML response.
        """
        course = sample_courses["free"]
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")

        # Preview lesson details should be visible
        assert "1. Introduction Video" in content
        assert "Preview Available" in content

        # Non-preview lesson title is visible with locked icon
        assert "2. Secret Advanced Lesson" in content
        assert "Locked" in content

        # CRITICAL: The non-preview secret video ID must NOT appear anywhere in the HTML
        assert "bunny-secret-video-guid-99999" not in content

        # Unpublished lesson should not be in the syllabus at all
        assert "3. Unpublished Draft Lesson" not in content

    def test_json_ld_escapes_script_tags(self, client: Client):
        """
        Ensure JSON-LD generation safely escapes </script> tags to prevent XSS.
        """
        malicious_course = Course.objects.create(
            title="Course with </script><script>alert('xss')</script> in title",
            slug="xss-test-course",
            short_description="Testing </script> breakout safety.",
            description="Safe description",
            is_published=True,
            is_free=True,
        )
        resp = client.get(reverse("courses:detail", kwargs={"slug": malicious_course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")

        # Ensure raw unescaped </script> from course title is not closing the JSON-LD script block
        assert "</script><script>alert" not in content
        assert "\\u003c/script\\u003e" in content

    def test_query_count_is_bounded_no_n_plus_one(self, client: Client, django_assert_num_queries):
        """
        Verify that course list queries are optimized and do not suffer from N+1 query multiplication.
        """
        # Create 10 published courses with lessons
        for i in range(10):
            c = Course.objects.create(
                title=f"Bulk Course {i}",
                slug=f"bulk-course-{i}",
                is_published=True,
                is_free=True,
            )
            for j in range(3):
                Lesson.objects.create(
                    course=c,
                    title=f"Lesson {j}",
                    order=j + 1,
                    is_published=True,
                )

        # Prime settings singleton so we measure only course queries
        SiteSettings.get_solo()

        url = reverse("courses:list")
        # Ensure total course queries stay bounded (count query + page items with distinct annotations)
        with django_assert_num_queries(3, exact=False):
            response = client.get(url)
            assert response.status_code == 200
