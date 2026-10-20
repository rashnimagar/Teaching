import pytest

from apps.courses.models import Lesson
from apps.courses.services.video import build_safe_video_embed_url, generate_bunny_token


class TestVideoEmbedService:
    def test_youtube_valid_embed_url(self):
        url = build_safe_video_embed_url(Lesson.VideoProvider.YOUTUBE, "dQw4w9WgXcQ")
        assert url == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"

    def test_youtube_invalid_id_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid YouTube video ID format"):
            build_safe_video_embed_url(Lesson.VideoProvider.YOUTUBE, "short_id")

        with pytest.raises(ValueError, match="Invalid YouTube video ID format"):
            build_safe_video_embed_url(Lesson.VideoProvider.YOUTUBE, "bad<script>id")

    def test_vimeo_valid_embed_url_without_hash(self):
        url = build_safe_video_embed_url(Lesson.VideoProvider.VIMEO, "76979871")
        assert url == "https://player.vimeo.com/video/76979871?dnt=1"

    def test_vimeo_valid_embed_url_with_privacy_hash(self):
        url = build_safe_video_embed_url(
            Lesson.VideoProvider.VIMEO, "76979871", video_hash="d7a12b45e8"
        )
        assert url == "https://player.vimeo.com/video/76979871?h=d7a12b45e8&dnt=1"

    def test_vimeo_invalid_hash_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid Vimeo video hash format"):
            build_safe_video_embed_url(
                Lesson.VideoProvider.VIMEO, "76979871", video_hash="bad/hash/with/slashes"
            )

    def test_bunny_valid_embed_url_unsigned_by_default(self, settings):
        settings.BUNNY_STREAM_LIBRARY_ID = "12345"
        settings.BUNNY_STREAM_SIGNING_ENABLED = False
        url = build_safe_video_embed_url(
            Lesson.VideoProvider.BUNNY, "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )
        assert (
            url
            == "https://iframe.mediadelivery.net/embed/12345/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )

    def test_bunny_signed_url_when_enabled(self, settings):
        settings.BUNNY_STREAM_LIBRARY_ID = "12345"
        settings.BUNNY_STREAM_TOKEN_KEY = "test-secret-token-key"
        settings.BUNNY_STREAM_SIGNING_ENABLED = True
        url = build_safe_video_embed_url(
            Lesson.VideoProvider.BUNNY, "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )
        assert url.startswith(
            "https://iframe.mediadelivery.net/embed/12345/a1b2c3d4-e5f6-7890-abcd-ef1234567890?"
        )
        assert "token=" in url
        assert "expires=" in url

    def test_bunny_token_generation_formula(self):
        token, expires = generate_bunny_token(
            library_id="12345",
            video_id="video-guid-001",
            token_key="sec-key",
            expires_in=600,
        )
        assert len(token) == 64  # SHA256 hex length
        assert expires > 0

    def test_empty_video_id_returns_empty_string(self):
        assert build_safe_video_embed_url(Lesson.VideoProvider.YOUTUBE, "") == ""
        assert build_safe_video_embed_url(Lesson.VideoProvider.VIMEO, "   ") == ""

    def test_unsupported_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported video provider"):
            build_safe_video_embed_url("dailymotion", "12345678901")


class TestVideoExtractor:
    def test_extract_youtube_standard_watch_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"
        info = extract_video_info(url)
        assert info["video_id"] == "dQw4w9WgXcQ"
        assert info["provider"] == Lesson.VideoProvider.YOUTUBE
        assert info["video_hash"] == ""

    def test_extract_youtube_short_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://youtu.be/dQw4w9WgXcQ?si=abcdef12345"
        info = extract_video_info(url)
        assert info["video_id"] == "dQw4w9WgXcQ"
        assert info["provider"] == Lesson.VideoProvider.YOUTUBE

    def test_extract_youtube_embed_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        info = extract_video_info(url)
        assert info["video_id"] == "dQw4w9WgXcQ"
        assert info["provider"] == Lesson.VideoProvider.YOUTUBE

    def test_extract_youtube_shorts_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share"
        info = extract_video_info(url)
        assert info["video_id"] == "dQw4w9WgXcQ"
        assert info["provider"] == Lesson.VideoProvider.YOUTUBE

    def test_extract_vimeo_with_path_hash(self):
        from apps.courses.services.video import extract_video_info

        url = "https://vimeo.com/76979871/d7a12b45e8"
        info = extract_video_info(url)
        assert info["video_id"] == "76979871"
        assert info["provider"] == Lesson.VideoProvider.VIMEO
        assert info["video_hash"] == "d7a12b45e8"

    def test_extract_vimeo_with_query_hash(self):
        from apps.courses.services.video import extract_video_info

        url = "https://vimeo.com/76979871?h=d7a12b45e8"
        info = extract_video_info(url)
        assert info["video_id"] == "76979871"
        assert info["provider"] == Lesson.VideoProvider.VIMEO
        assert info["video_hash"] == "d7a12b45e8"

    def test_extract_vimeo_plain_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://vimeo.com/76979871"
        info = extract_video_info(url)
        assert info["video_id"] == "76979871"
        assert info["provider"] == Lesson.VideoProvider.VIMEO
        assert info["video_hash"] == ""

    def test_extract_bunny_mediadelivery_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://iframe.mediadelivery.net/embed/12345/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        info = extract_video_info(url)
        assert info["video_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert info["provider"] == Lesson.VideoProvider.BUNNY

    def test_extract_bunny_play_url(self):
        from apps.courses.services.video import extract_video_info

        url = "https://video.bunnycdn.com/play/12345/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        info = extract_video_info(url)
        assert info["video_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert info["provider"] == Lesson.VideoProvider.BUNNY

    def test_extract_plain_id_preserves_provider(self):
        from apps.courses.services.video import extract_video_info

        info = extract_video_info("dQw4w9WgXcQ", current_provider=Lesson.VideoProvider.YOUTUBE)
        assert info["video_id"] == "dQw4w9WgXcQ"
        assert info["provider"] == Lesson.VideoProvider.YOUTUBE

    def test_extract_empty_string(self):
        from apps.courses.services.video import extract_video_info

        info = extract_video_info("", current_provider="youtube")
        assert info["video_id"] == ""
        assert info["provider"] == "youtube"


@pytest.mark.django_db
class TestLessonAdminFeatures:
    def test_embed_preview_renders_sandboxed_iframe(self):
        from django.contrib.admin.sites import AdminSite

        from apps.courses.admin import LessonAdmin
        from apps.courses.models import Course, Lesson

        site = AdminSite()
        admin_instance = LessonAdmin(Lesson, site)

        course = Course.objects.create(title="Admin Course", slug="admin-course")
        lesson = Lesson.objects.create(
            course=course,
            title="Preview Lesson",
            order=1,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
        )

        preview_html = str(admin_instance.embed_preview(lesson))
        assert "<iframe" in preview_html
        assert "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0" in preview_html
        expected_sandbox = (
            'sandbox="allow-scripts allow-same-origin allow-presentation '
            'allow-popups allow-popups-to-escape-sandbox"'
        )
        assert expected_sandbox in preview_html

    def test_embed_preview_handles_empty_video_id(self):
        from django.contrib.admin.sites import AdminSite

        from apps.courses.admin import LessonAdmin
        from apps.courses.models import Course, Lesson

        site = AdminSite()
        admin_instance = LessonAdmin(Lesson, site)
        course = Course.objects.create(title="Admin Course 2", slug="admin-course-2")
        lesson = Lesson(course=course, title="No Video", video_id="")

        preview = str(admin_instance.embed_preview(lesson))
        assert "Save with a valid video ID to see an embed preview." in preview

    def test_lesson_admin_form_extracts_full_url(self):
        from apps.courses.admin import LessonAdminForm
        from apps.courses.models import Course

        course = Course.objects.create(title="Admin Course 3", slug="admin-course-3")
        form = LessonAdminForm(
            data={
                "course": course.id,
                "title": "Form Cleaned Lesson",
                "order": 1,
                "video_provider": "bunny",  # Should be overridden by URL
                "video_id": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "is_published": True,
            }
        )
        assert form.is_valid(), form.errors
        saved_lesson = form.save()
        assert saved_lesson.video_id == "dQw4w9WgXcQ"
        assert saved_lesson.video_provider == "youtube"
