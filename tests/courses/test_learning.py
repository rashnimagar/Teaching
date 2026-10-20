import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress


@pytest.fixture
def active_course(db):
    return Course.objects.create(
        title="Django Masterclass",
        slug="django-masterclass",
        short_description="Learn Django step by step",
        description="Comprehensive course.",
        is_published=True,
        is_free=True,
    )


@pytest.fixture
def published_lessons(active_course):
    l1 = Lesson.objects.create(
        course=active_course,
        title="1. Introduction",
        order=1,
        video_provider=Lesson.VideoProvider.YOUTUBE,
        video_id="dQw4w9WgXcQ",
        is_preview=True,
        is_published=True,
    )
    l2 = Lesson.objects.create(
        course=active_course,
        title="2. Deep Dive",
        order=2,
        video_provider=Lesson.VideoProvider.YOUTUBE,
        video_id="abc123xyz78",
        is_preview=False,
        is_published=True,
    )
    return l1, l2


@pytest.mark.django_db
class TestLessonAccessControl:
    def test_anonymous_redirected_to_login(self, client, active_course, published_lessons):
        l1, l2 = published_lessons
        resp = client.get(reverse("learn:course", kwargs={"course_slug": active_course.slug}))
        assert resp.status_code == 302
        assert reverse("account_login") in resp.url

        resp_lesson = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l1.id})
        )
        assert resp_lesson.status_code == 302
        assert reverse("account_login") in resp_lesson.url

    def test_student_with_active_enrollment_can_access_lessons(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=student, course=active_course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(student)

        l1, l2 = published_lessons
        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l2.id})
        )
        assert resp.status_code == 200
        assert "abc123xyz78" in resp.content.decode("utf-8")
        assert resp.headers["Cache-Control"] == "private, no-store"

    def test_student_without_enrollment_can_access_preview_lesson_only(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        client.force_login(student)

        l1, l2 = published_lessons
        # Preview lesson accessible
        resp_preview = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l1.id})
        )
        assert resp_preview.status_code == 200

        # Locked lesson redirects to course detail
        resp_locked = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l2.id})
        )
        assert resp_locked.status_code == 302
        assert resp_locked.url == reverse("courses:detail", kwargs={"slug": active_course.slug})

    def test_pending_and_revoked_enrollment_redirected_from_locked_lesson(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        enrollment = Enrollment.objects.create(
            student=student, course=active_course, status=Enrollment.Status.PENDING
        )
        client.force_login(student)

        _, l2 = published_lessons
        resp_pending = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l2.id})
        )
        assert resp_pending.status_code == 302
        assert resp_pending.url == reverse("courses:detail", kwargs={"slug": active_course.slug})

        # Revoked enrollment
        enrollment.status = Enrollment.Status.REVOKED
        enrollment.save()
        resp_revoked = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l2.id})
        )
        assert resp_revoked.status_code == 302
        assert resp_revoked.url == reverse("courses:detail", kwargs={"slug": active_course.slug})

    def test_locked_lesson_video_id_and_embed_never_appear_in_html(
        self, client, user_factory, active_course, published_lessons
    ):
        """
        Verify that unenrolled, pending, and revoked users never see locked lesson video IDs
        or embed URLs anywhere in the rendered HTML.
        """
        student = user_factory(role=User.Role.STUDENT)
        client.force_login(student)

        l1, l2 = published_lessons
        # View preview lesson
        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": active_course.slug, "lesson_id": l1.id})
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert l1.video_id in html
        assert l2.video_id not in html
        assert "abc123xyz78" not in html

    def test_unpublished_lesson_returns_404_for_students(self, client, user_factory, active_course):
        unpub_lesson = Lesson.objects.create(
            course=active_course,
            title="Unpublished Draft",
            order=99,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="unpub123456",
            is_published=False,
        )
        student = user_factory(role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=student, course=active_course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(student)

        resp = client.get(
            reverse(
                "learn:lesson",
                kwargs={"course_slug": active_course.slug, "lesson_id": unpub_lesson.id},
            )
        )
        assert resp.status_code == 404

        # Staff can view unpublished lesson
        staff = user_factory(email="staff@example.com", role=User.Role.TEACHER, is_staff=True)
        client.force_login(staff)
        resp_staff = client.get(
            reverse(
                "learn:lesson",
                kwargs={"course_slug": active_course.slug, "lesson_id": unpub_lesson.id},
            )
        )
        assert resp_staff.status_code == 200

    def test_archived_course_accessible_to_active_enrolled_students(
        self, client, user_factory, published_lessons
    ):
        l1, l2 = published_lessons
        course = l1.course
        course.is_archived = True
        course.save()

        # Active student retains access
        active_student = user_factory(email="active@example.com", role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=active_student, course=course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(active_student)

        resp = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp.status_code == 200

        # Unenrolled student gets 404
        other_student = user_factory(email="other@example.com", role=User.Role.STUDENT)
        client.force_login(other_student)
        resp_other = client.get(
            reverse("learn:lesson", kwargs={"course_slug": course.slug, "lesson_id": l1.id})
        )
        assert resp_other.status_code == 404

    def test_video_coming_soon_state_rendered_when_video_id_empty(
        self, client, user_factory, active_course
    ):
        no_video_lesson = Lesson.objects.create(
            course=active_course,
            title="Lesson Without Video Yet",
            order=10,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="",
            is_preview=True,
            is_published=True,
        )
        student = user_factory()
        client.force_login(student)

        resp = client.get(
            reverse(
                "learn:lesson",
                kwargs={"course_slug": active_course.slug, "lesson_id": no_video_lesson.id},
            )
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "Video Coming Soon" in html
        assert "<iframe" not in html
        assert "Video not loading?" not in html


@pytest.mark.django_db
class TestLessonPlayerRendering:
    def test_sandbox_tokens_and_attributes_rendered_for_youtube(
        self, client, user_factory, active_course
    ):
        lesson = Lesson.objects.create(
            course=active_course,
            title="YouTube Lesson",
            order=1,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
            is_preview=True,
            is_published=True,
        )
        student = user_factory()
        client.force_login(student)

        resp = client.get(
            reverse(
                "learn:lesson",
                kwargs={"course_slug": active_course.slug, "lesson_id": lesson.id},
            )
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        # 1. Assert iframe sandbox attribute with all 5 tokens
        expected_sandbox = (
            'sandbox="allow-scripts allow-same-origin allow-presentation '
            'allow-popups allow-popups-to-escape-sandbox"'
        )
        assert expected_sandbox in html
        assert (
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture; web-share"' in html
        )
        assert 'referrerpolicy="strict-origin-when-cross-origin"' in html
        assert 'loading="lazy"' in html

        # 2. Assert YouTube fallback line
        assert "Video not loading?" in html
        assert 'href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html
        assert "Open on YouTube" in html

    def test_sandbox_tokens_rendered_for_vimeo_without_youtube_fallback(
        self, client, user_factory, active_course
    ):
        lesson = Lesson.objects.create(
            course=active_course,
            title="Vimeo Lesson",
            order=2,
            video_provider=Lesson.VideoProvider.VIMEO,
            video_id="76979871",
            video_hash="d7a12b45e8",
            is_preview=True,
            is_published=True,
        )
        student = user_factory()
        client.force_login(student)

        resp = client.get(
            reverse(
                "learn:lesson",
                kwargs={"course_slug": active_course.slug, "lesson_id": lesson.id},
            )
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        expected_sandbox = (
            'sandbox="allow-scripts allow-same-origin allow-presentation '
            'allow-popups allow-popups-to-escape-sandbox"'
        )
        assert expected_sandbox in html
        assert "https://player.vimeo.com/video/76979871?h=d7a12b45e8&amp;dnt=1" in html

        # YouTube fallback line must NOT appear for Vimeo
        assert "Video not loading?" not in html
        assert "Open on YouTube" not in html

    def test_sandbox_tokens_rendered_for_bunny_without_youtube_fallback(
        self, client, user_factory, active_course, settings
    ):
        settings.BUNNY_STREAM_LIBRARY_ID = "12345"
        settings.BUNNY_STREAM_SIGNING_ENABLED = False

        lesson = Lesson.objects.create(
            course=active_course,
            title="Bunny Lesson",
            order=3,
            video_provider=Lesson.VideoProvider.BUNNY,
            video_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            is_preview=True,
            is_published=True,
        )
        student = user_factory()
        client.force_login(student)

        resp = client.get(
            reverse(
                "learn:lesson",
                kwargs={"course_slug": active_course.slug, "lesson_id": lesson.id},
            )
        )
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")

        expected_sandbox = (
            'sandbox="allow-scripts allow-same-origin allow-presentation '
            'allow-popups allow-popups-to-escape-sandbox"'
        )
        assert expected_sandbox in html
        assert (
            "https://iframe.mediadelivery.net/embed/12345/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            in html
        )

        # YouTube fallback line must NOT appear for Bunny
        assert "Video not loading?" not in html
        assert "Open on YouTube" not in html


@pytest.mark.django_db
class TestProgressEndpoints:
    def test_toggle_complete_updates_progress_and_returns_percentage(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=student, course=active_course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(student)

        l1, l2 = published_lessons
        url = reverse(
            "learn:toggle_complete", kwargs={"course_slug": active_course.slug, "lesson_id": l1.id}
        )

        # 1. Mark complete
        resp = client.post(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed"] is True
        assert data["completed_count"] == 1
        assert data["total_count"] == 2
        assert data["progress_percentage"] == 50

        # Verify DB
        progress = LessonProgress.objects.get(student=student, lesson=l1)
        assert progress.completed_at is not None

        # 2. Mark incomplete
        resp2 = client.post(url)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["completed"] is False
        assert data2["completed_count"] == 0
        assert data2["progress_percentage"] == 0

    def test_playback_position_saved_and_validated(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=student, course=active_course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(student)

        l1, _ = published_lessons
        url = reverse(
            "learn:playback_position",
            kwargs={"course_slug": active_course.slug, "lesson_id": l1.id},
        )

        # Valid position
        resp = client.post(url, {"position": 125})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["position"] == 125

        progress = LessonProgress.objects.get(student=student, lesson=l1)
        assert progress.last_position_seconds == 125

        # Invalid positions
        assert client.post(url, {"position": -10}).status_code == 400
        assert client.post(url, {"position": 999999}).status_code == 400
        assert client.post(url, {"position": "not_a_number"}).status_code == 400

    def test_progress_posts_rejected_for_users_without_access(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        client.force_login(student)

        _, l2 = published_lessons  # l2 is locked (not preview)
        toggle_url = reverse(
            "learn:toggle_complete", kwargs={"course_slug": active_course.slug, "lesson_id": l2.id}
        )
        pos_url = reverse(
            "learn:playback_position",
            kwargs={"course_slug": active_course.slug, "lesson_id": l2.id},
        )

        assert client.post(toggle_url).status_code == 403
        assert client.post(pos_url, {"position": 50}).status_code == 403

    def test_user_keyed_rate_limit_does_not_affect_second_user_on_same_ip(
        self, client, user_factory, active_course, published_lessons
    ):
        """
        Verify that rate limiting on progress endpoints is keyed by user,
        so a classroom sharing one IP is not throttled together.
        """
        user_a = user_factory(email="user_a@example.com", role=User.Role.STUDENT)
        user_b = user_factory(email="user_b@example.com", role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=user_a, course=active_course, status=Enrollment.Status.ACTIVE
        )
        Enrollment.objects.create(
            student=user_b, course=active_course, status=Enrollment.Status.ACTIVE
        )

        l1, _ = published_lessons
        url = reverse(
            "learn:playback_position",
            kwargs={"course_slug": active_course.slug, "lesson_id": l1.id},
        )

        # User A makes 120 requests from 192.168.1.1
        client.force_login(user_a)
        for _ in range(120):
            r = client.post(url, {"position": 10}, REMOTE_ADDR="192.168.1.1")
            assert r.status_code == 200

        # User A 121st request hits 429
        r_exceeded = client.post(url, {"position": 10}, REMOTE_ADDR="192.168.1.1")
        assert r_exceeded.status_code == 429

        # User B makes a request from the EXACT SAME IP address -> must succeed (200)
        client.force_login(user_b)
        r_b = client.post(url, {"position": 10}, REMOTE_ADDR="192.168.1.1")
        assert r_b.status_code == 200

    def test_learn_redirect_router_resolves_appropriate_lesson(
        self, client, user_factory, active_course, published_lessons
    ):
        student = user_factory(role=User.Role.STUDENT)
        Enrollment.objects.create(
            student=student, course=active_course, status=Enrollment.Status.ACTIVE
        )
        client.force_login(student)

        l1, l2 = published_lessons
        learn_url = reverse("learn:course", kwargs={"course_slug": active_course.slug})

        # First visit: redirects to l1
        resp = client.get(learn_url)
        assert resp.status_code == 302
        assert str(l1.id) in resp.url

        # Mark l1 complete -> redirects to l2
        LessonProgress.objects.create(student=student, lesson=l1, completed_at=timezone_now())
        resp2 = client.get(learn_url)
        assert resp2.status_code == 302
        assert str(l2.id) in resp2.url

    def test_lesson_learn_page_query_count_does_not_grow_with_lessons(self, client, user_factory):
        """
        Verify that database queries on the lesson learning page do not scale
        with the number of lessons in the syllabus (comparing 1 lesson vs 10 lessons).
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        student = user_factory(email="learner@example.com", role=User.Role.STUDENT)
        client.force_login(student)

        # Course A with 1 lesson
        course_a = Course.objects.create(
            title="Course A", slug="course-a", is_published=True, is_free=True
        )
        la1 = Lesson.objects.create(course=course_a, title="A1", order=1, is_published=True)
        Enrollment.objects.create(student=student, course=course_a, status=Enrollment.Status.ACTIVE)

        # Warm up
        client.get(
            reverse("learn:lesson", kwargs={"course_slug": course_a.slug, "lesson_id": la1.id})
        )

        with CaptureQueriesContext(connection) as captured_1:
            client.get(
                reverse("learn:lesson", kwargs={"course_slug": course_a.slug, "lesson_id": la1.id})
            )
        query_count_1 = len(captured_1)

        # Course B with 10 lessons
        course_b = Course.objects.create(
            title="Course B", slug="course-b", is_published=True, is_free=True
        )
        lb_first = None
        for i in range(1, 11):
            lb = Lesson.objects.create(course=course_b, title=f"B{i}", order=i, is_published=True)
            if i == 1:
                lb_first = lb
        Enrollment.objects.create(student=student, course=course_b, status=Enrollment.Status.ACTIVE)

        # Warm up
        client.get(
            reverse("learn:lesson", kwargs={"course_slug": course_b.slug, "lesson_id": lb_first.id})
        )

        with CaptureQueriesContext(connection) as captured_10:
            client.get(
                reverse(
                    "learn:lesson", kwargs={"course_slug": course_b.slug, "lesson_id": lb_first.id}
                )
            )
        query_count_10 = len(captured_10)

        assert query_count_1 == query_count_10


def timezone_now():
    from django.utils import timezone

    return timezone.now()
