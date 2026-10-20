from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.core.models import FAQItem, SiteSettings
from apps.courses.models import Course, Enrollment, Lesson

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_site_settings_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestTeacherSectionVisibility:
    def test_teacher_section_visible_when_both_name_and_bio_are_set(self, client: Client):
        settings = SiteSettings.get_solo()
        settings.teacher_name = "Pradeep Sharma"
        settings.teacher_title = "Lead Software Instructor"
        settings.teacher_bio = "Over 10 years of experience building production software systems."
        settings.save()

        response = client.get(reverse("core:home"))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'id="instructor-section"' in content
        assert "Pradeep Sharma" in content
        assert "Lead Software Instructor" in content
        assert "Over 10 years of experience" in content

    def test_teacher_section_hidden_when_bio_is_empty(self, client: Client):
        settings = SiteSettings.get_solo()
        settings.teacher_name = "Pradeep Sharma"
        settings.teacher_bio = ""
        settings.save()

        response = client.get(reverse("core:home"))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'id="instructor-section"' not in content
        assert "Pradeep Sharma" not in content

    def test_teacher_section_hidden_when_name_is_empty(self, client: Client):
        settings = SiteSettings.get_solo()
        settings.teacher_name = ""
        settings.teacher_bio = "Passionate educator with years of teaching experience."
        settings.save()

        response = client.get(reverse("core:home"))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'id="instructor-section"' not in content

    def test_teacher_section_hidden_when_both_are_empty(self, client: Client):
        settings = SiteSettings.get_solo()
        settings.teacher_name = ""
        settings.teacher_bio = ""
        settings.save()

        response = client.get(reverse("core:home"))
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert 'id="instructor-section"' not in content


@pytest.mark.django_db
class TestRenderEdgeCases:
    def test_course_with_very_long_title_and_description(self, client: Client):
        long_title = (
            "Complete Enterprise Full-Stack Python Django and Modern Vanilla JavaScript "
            "Mastery Course with High Availability Microservices and Production Deployments"
        )
        course = Course.objects.create(
            title=long_title,
            slug="complete-enterprise-full-stack-python",
            short_description="A" * 300,
            description="B" * 1000,
            is_published=True,
            is_free=True,
        )
        Lesson.objects.create(
            course=course,
            title="Lesson 1",
            order=1,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="video123",
            is_published=True,
        )

        # Test catalog
        resp_list = client.get(reverse("courses:list"))
        assert resp_list.status_code == 200
        assert long_title in resp_list.content.decode("utf-8")

        # Test detail page
        resp_detail = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp_detail.status_code == 200
        assert long_title in resp_detail.content.decode("utf-8")

    def test_course_with_nepali_title_renders_monogram_conjunct(self, client: Client):
        nepali_title = "नेपाली भाषामा आधुनिक वेब विकास र प्रोग्रामिङ"
        Course.objects.create(
            title=nepali_title,
            slug="nepali-web-dev",
            short_description="नेपाली भाषामा कोडिङ सिक्नुहोस्।",
            is_published=True,
            is_free=True,
        )

        resp = client.get(reverse("courses:list"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert nepali_title in content
        # Monogram for "नेपाली" should contain the grapheme "ने"
        assert "ने" in content

    def test_course_without_thumbnail_renders_fallback_gradient(self, client: Client):
        Course.objects.create(
            title="Course Without Image",
            slug="no-thumb-course",
            short_description="Testing fallback monogram gradient.",
            is_published=True,
            is_free=True,
        )
        resp = client.get(reverse("courses:list"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "from-indigo-600 via-indigo-700 to-slate-900" in content
        assert "Video Course" in content

    def test_user_without_first_name_renders_avatar_without_error(self, client: Client):
        user = User.objects.create_user(
            email="nameless@example.com",
            password="SecurePassword123!",
            first_name="",
            last_name="",
        )
        client.force_login(user)
        resp = client.get(reverse("core:home"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        # Header shows fallback to email initial "N"
        assert "nameless@example.com" in content
        assert "Sign out" in content

    def test_catalog_with_zero_courses(self, client: Client):
        resp = client.get(reverse("courses:list"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "No courses found" in content
        assert "Reset All Filters" in content

    def test_catalog_with_one_course(self, client: Client):
        Course.objects.create(
            title="Single Standalone Course",
            slug="single-course",
            is_published=True,
            is_free=True,
        )
        resp = client.get(reverse("courses:list"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Single Standalone Course" in content
        # With 1 course, pagination is not shown
        assert 'aria-label="Course catalog pagination"' not in content

    def test_catalog_with_twenty_courses_paginated(self, client: Client):
        for i in range(1, 21):
            is_free = i % 2 == 0
            Course.objects.create(
                title=f"Course Number {i:02d}",
                slug=f"course-{i:02d}",
                is_published=True,
                is_free=is_free,
                price=Decimal("1000.00") if not is_free else Decimal("0.00"),
                currency="NPR",
            )
        resp = client.get(reverse("courses:list"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        # Ordered by -created_at: latest courses appear on page 1
        assert "Course Number 20" in content
        # Page size is 9 courses per page, so 20 courses yields page 1 of 3
        assert "Page 1 of 3" in content
        assert "Next &rarr;" in content

        # Page 3 contains the earliest created course
        resp_p3 = client.get(reverse("courses:list") + "?page=3")
        assert resp_p3.status_code == 200
        content_p3 = resp_p3.content.decode("utf-8")
        assert "Course Number 01" in content_p3
        assert "&larr; Previous" in content_p3

    def test_faq_accordion_renders_faq_item_data(self, client: Client):
        FAQItem.objects.create(
            question="What prerequisites are required?",
            answer="Basic computer literacy is sufficient for introductory tracks.",
            order=1,
            is_published=True,
        )
        resp = client.get(reverse("core:home"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "What prerequisites are required?" in content
        assert "Basic computer literacy" in content
        assert "<details" in content
        assert "<summary" in content


@pytest.mark.django_db
class TestCourseDetailAllEnrollmentStates:
    def test_guest_sees_login_to_enroll(self, client: Client):
        course = Course.objects.create(
            title="Open Public Course",
            slug="open-course",
            is_published=True,
            is_free=True,
        )
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Log in to Enroll" in content

    def test_active_enrolled_student_sees_continue_learning(self, client: Client):
        course = Course.objects.create(
            title="Enrolled Course",
            slug="enrolled-course",
            is_published=True,
            is_free=True,
        )
        student = User.objects.create_user(
            email="active_student@example.com",
            password="Password123!",
        )
        Enrollment.objects.create(
            student=student,
            course=course,
            status=Enrollment.Status.ACTIVE,
        )
        client.force_login(student)
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Continue Learning &rarr;" in content
        assert "You are enrolled" in content

    def test_pending_enrollment_shows_pending_status(self, client: Client):
        course = Course.objects.create(
            title="Approval Course",
            slug="approval-course",
            is_published=True,
            is_free=True,
            requires_approval=True,
        )
        student = User.objects.create_user(
            email="pending_student@example.com",
            password="Password123!",
        )
        Enrollment.objects.create(
            student=student,
            course=course,
            status=Enrollment.Status.PENDING,
        )
        client.force_login(student)
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Enrollment Pending" in content

    def test_revoked_enrollment_shows_revoked_notice(self, client: Client):
        course = Course.objects.create(
            title="Revoked Course",
            slug="revoked-course",
            is_published=True,
            is_free=True,
        )
        student = User.objects.create_user(
            email="revoked_student@example.com",
            password="Password123!",
        )
        Enrollment.objects.create(
            student=student,
            course=course,
            status=Enrollment.Status.REVOKED,
        )
        client.force_login(student)
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Access removed, please contact the teacher." in content

    def test_paid_course_shows_enrollment_opens_soon(self, client: Client):
        course = Course.objects.create(
            title="Paid Masterclass",
            slug="paid-masterclass",
            is_published=True,
            is_free=False,
            price=Decimal("4999.00"),
            currency="NPR",
        )
        student = User.objects.create_user(
            email="paid_buyer@example.com",
            password="Password123!",
        )
        client.force_login(student)
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Enrollment opens soon" in content

    def test_free_with_approval_shows_request_enrollment(self, client: Client):
        course = Course.objects.create(
            title="Gated Free Course",
            slug="gated-free-course",
            is_published=True,
            is_free=True,
            requires_approval=True,
        )
        student = User.objects.create_user(
            email="requester@example.com",
            password="Password123!",
        )
        client.force_login(student)
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Request Enrollment" in content

    def test_archived_course_shows_archived_badge_for_enrolled_student(self, client: Client):
        course = Course.objects.create(
            title="Archived Old Course",
            slug="archived-old-course",
            is_published=True,
            is_archived=True,
            is_free=True,
        )
        student = User.objects.create_user(
            email="archived_learner@example.com",
            password="Password123!",
        )
        Enrollment.objects.create(
            student=student,
            course=course,
            status=Enrollment.Status.ACTIVE,
        )
        client.force_login(student)
        resp = client.get(reverse("courses:detail", kwargs={"slug": course.slug}))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Archived Course" in content
        assert "Continue Learning &rarr;" in content
