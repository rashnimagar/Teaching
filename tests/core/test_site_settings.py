import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.core.models import SiteSettings


@pytest.mark.django_db
class TestSiteSettingsSingleton:
    def test_get_solo_returns_singleton_with_neutral_defaults(self):
        settings_obj = SiteSettings.get_solo()
        assert settings_obj.pk == 1
        assert settings_obj.site_name == "Teaching Platform"
        # Verify neutral defaults (no fake person)
        assert settings_obj.teacher_name == ""
        assert settings_obj.teacher_bio == ""
        assert settings_obj.teacher_title == ""

    def test_save_enforces_singleton_pk(self):
        s1 = SiteSettings.get_solo()
        s1.site_name = "Custom Academy"
        s1.save()

        # Attempt to create another instance with different pk
        s2 = SiteSettings(pk=2, site_name="Second Instance")
        s2.save()

        assert SiteSettings.objects.count() == 1
        current = SiteSettings.get_solo()
        assert current.pk == 1
        assert current.site_name == "Second Instance"

    def test_save_invalidates_cache(self):
        SiteSettings.get_solo()
        assert cache.get(SiteSettings.CACHE_KEY) is not None

        s = SiteSettings.get_solo()
        s.site_name = "Invalidated Academy"
        s.save()

        # Cache key must be cleared on save
        assert cache.get(SiteSettings.CACHE_KEY) is None

        # Next call repopulates cache with updated value
        reloaded = SiteSettings.get_solo()
        assert reloaded.site_name == "Invalidated Academy"
        assert cache.get(SiteSettings.CACHE_KEY) is not None

    def test_about_section_hidden_when_teacher_name_or_bio_is_blank(self, client: Client):
        s = SiteSettings.get_solo()
        s.teacher_name = ""
        s.teacher_bio = ""
        s.save()

        resp = client.get(reverse("core:home"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "Instructor Profile" not in content

        # Set only teacher name, bio still blank
        s.teacher_name = "Jane Instructor"
        s.teacher_bio = ""
        s.save()

        resp = client.get(reverse("core:home"))
        content = resp.content.decode("utf-8")
        assert "Instructor Profile" not in content
        assert "Jane Instructor" not in content

    def test_about_section_displayed_when_teacher_name_and_bio_are_filled(self, client: Client):
        s = SiteSettings.get_solo()
        s.teacher_name = "Prof. Jane Doe"
        s.teacher_title = "Lead Software Instructor"
        s.teacher_bio = "Over 15 years building distributed systems and teaching developers."
        s.contact_email = "jane@example.com"
        s.save()

        resp = client.get(reverse("core:home"))
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")

        assert "Instructor Profile" in content
        assert "Prof. Jane Doe" in content
        assert "Lead Software Instructor" in content
        assert "Over 15 years building distributed systems" in content
        assert "Contact email:" in content
        assert "jane@example.com" in content

    def test_site_settings_context_processor_resilient_to_db_error(self, rf):
        from unittest.mock import patch

        from django.db import OperationalError

        from apps.core.context_processors import site_settings as site_settings_cp

        request = rf.get("/")
        cache.clear()

        with patch(
            "apps.core.models.SiteSettings.objects.get_or_create",
            side_effect=OperationalError("no such table"),
        ):
            ctx = site_settings_cp(request)
            assert "site_settings" in ctx
            assert ctx["site_settings"].site_name == "Teaching Platform"

    def test_page_renders_gracefully_when_site_settings_table_is_missing(self, client: Client):
        from unittest.mock import patch

        from django.db import OperationalError

        cache.clear()
        with patch(
            "apps.core.models.SiteSettings.objects.get_or_create",
            side_effect=OperationalError("no such table"),
        ):
            resp = client.get(reverse("core:home"))
            assert resp.status_code == 200
            assert "Teaching Platform" in resp.content.decode("utf-8")
