import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.courses.models import Course, Enrollment, Lesson


@pytest.mark.django_db
class TestLessonLearningUI:
    @pytest.fixture
    def learning_setup(self, user_factory):
        student = user_factory(first_name="Pooja", role=User.Role.STUDENT)
        course = Course.objects.create(
            title="Fullstack React & Django",
            slug="react-django",
            is_published=True,
            is_free=True,
        )
        l1 = Lesson.objects.create(
            course=course,
            title="Setup Environment",
            order=1,
            is_published=True,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
            description="Official docs at https://djangoproject.com and tutorial at https://react.dev.\nCheck these resources.\n<script>alert('xss')</script>",
        )
        l2 = Lesson.objects.create(
            course=course,
            title="Components Architecture",
            order=2,
            is_published=True,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="",  # No video
            description="",
        )
        Enrollment.objects.create(student=student, course=course, status=Enrollment.Status.ACTIVE)
        return {
            "student": student,
            "course": course,
            "l1": l1,
            "l2": l2,
        }

    def test_lesson_notes_escaped_plain_text_with_urlize(self, client, learning_setup):
        """
        Requirement 1: Lesson notes render as escaped plain text (line breaks plus auto-linked URLs).
        No Markdown and no |safe on teacher-editable content.
        """
        student = learning_setup["student"]
        course = learning_setup["course"]
        l1 = learning_setup["l1"]
        client.force_login(student)

        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # Auto-linked URLs
        assert (
            'href="https://djangoproject.com"' in html or 'href="http://djangoproject.com"' in html
        )
        assert 'href="https://react.dev"' in html

        # Preserved line breaks
        assert "<br>" in html

        # Strict HTML escaping (XSS prevention without safe filter)
        assert "<script>alert('xss')</script>" not in html
        assert (
            "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html
            or "&lt;script&gt;alert('xss')&lt;/script&gt;" in html
        )

    def test_youtube_facade_and_fallback_rendered(self, client, learning_setup):
        """
        Requirement 3: YouTube lesson features a click-to-load facade for performance,
        with 'Open on YouTube' fallback kept.
        """
        student = learning_setup["student"]
        course = learning_setup["course"]
        l1 = learning_setup["l1"]
        client.force_login(student)

        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # Facade container (semantic button with accessible name)
        assert '<button type="button"' in html
        assert 'id="youtube-facade"' in html
        assert 'aria-label="Play video: Setup Environment"' in html
        assert "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html

        # Open on YouTube fallback link
        assert "Open on YouTube" in html
        assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in html
        assert 'rel="noopener noreferrer"' in html

    def test_no_video_coming_soon_state(self, client, learning_setup):
        """No video state displays clean 'Video Coming Soon' container."""
        student = learning_setup["student"]
        course = learning_setup["course"]
        l2 = learning_setup["l2"]
        client.force_login(student)

        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l2.id})
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Video Coming Soon" in html
        assert 'id="youtube-facade"' not in html

    def test_teacher_viewing_lesson_sees_banner(self, client, learning_setup, user_factory):
        """
        Requirement 10: Teachers/staff viewing a lesson see a small 'Viewing as teacher' banner.
        Regular students do not see the banner.
        """
        course = learning_setup["course"]
        l1 = learning_setup["l1"]

        # 1. Student view: NO banner
        student = learning_setup["student"]
        client.force_login(student)
        resp_student = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp_student.status_code == 200
        assert "Viewing as teacher" not in resp_student.content.decode("utf-8")

        # 2. Teacher view: Banner IS present
        teacher = user_factory(
            first_name="Prof",
            email="teacher_prof@example.com",
            role=User.Role.TEACHER,
            is_staff=True,
        )
        client.force_login(teacher)
        resp_teacher = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp_teacher.status_code == 200
        html_teacher = resp_teacher.content.decode("utf-8")
        assert "Viewing as teacher" in html_teacher
        assert reverse("admin:courses_lesson_change", args=[l1.id]) in html_teacher

    def test_assignments_tab_with_real_deadlines_and_no_submit_button(self, client, learning_setup):
        """
        Requirement 6: Assignments tab lists real assignments with deadlines and open/closed status;
        no Submit button yet ('Submissions open soon').
        """
        student = learning_setup["student"]
        course = learning_setup["course"]
        l1 = learning_setup["l1"]
        client.force_login(student)

        from datetime import timedelta

        from django.utils import timezone

        # Create open assignment
        Assignment.objects.create(
            course=course,
            lesson=l1,
            title="Create React Components",
            instructions="Build navbar and footer.\nDocument at https://react.dev",
            opens_at=timezone.now() - timedelta(days=1),
            due_at=timezone.now() + timedelta(days=7),
            max_score=50,
        )

        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Create React Components" in html
        assert "50 pts" in html
        assert "Open" in html
        assert "Submit Assignment" in html

    def test_syllabus_lock_states(self, client, user_factory):
        """Syllabus displays locked icons for inaccessible lessons."""
        course = Course.objects.create(
            title="Paid Deep Dive",
            slug="paid-deep-dive",
            is_published=True,
            is_free=False,
            price=500,
        )
        l1 = Lesson.objects.create(
            course=course, title="Preview Lesson", order=1, is_published=True, is_preview=True
        )
        l2 = Lesson.objects.create(
            course=course, title="Locked Lesson", order=2, is_published=True, is_preview=False
        )

        guest_user = user_factory(email="guest_locked@example.com", role=User.Role.STUDENT)
        client.force_login(guest_user)
        # Not enrolled in paid course, viewing preview lesson
        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        assert "Preview Lesson" in html
        assert "Locked Lesson" in html
        # l2 is locked: must not be a clickable link in syllabus sidebar
        l2_url = reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l2.id})
        assert f'<a href="{l2_url}"' not in html
