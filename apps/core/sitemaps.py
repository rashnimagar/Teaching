from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.courses.models import Course


class SiteUrlSitemap(Sitemap):
    """
    Base Sitemap class ensuring absolute URLs strictly respect settings.SITE_URL.
    """

    def get_domain(self, site=None):
        parsed = urlparse(settings.SITE_URL)
        return parsed.netloc or "127.0.0.1:8000"

    def get_protocol(self, protocol=None):
        parsed = urlparse(settings.SITE_URL)
        return parsed.scheme or "http"


class StaticViewSitemap(SiteUrlSitemap):
    priority = 0.8
    changefreq = "daily"

    def items(self):
        return ["core:home", "courses:list", "core:privacy", "core:terms"]

    def location(self, item):
        return reverse(item)


class CourseSitemap(SiteUrlSitemap):
    priority = 1.0
    changefreq = "weekly"

    def items(self):
        return Course.objects.filter(is_published=True, is_archived=False).order_by("-updated_at")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse("courses:detail", kwargs={"slug": obj.slug})
