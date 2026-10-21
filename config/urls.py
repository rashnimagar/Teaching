from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic.base import RedirectView

from apps.accounts.views import rate_limited_admin_login_view
from apps.core.sitemaps import CourseSitemap, StaticViewSitemap
from apps.core.views import robots_txt_view
from apps.core.views_styleguide import styleguide_view

sitemaps = {
    "static": StaticViewSitemap,
    "courses": CourseSitemap,
}

urlpatterns = [
    path("admin/login/", rate_limited_admin_login_view, name="admin_login"),
    path("admin/", admin.site.urls),
    path(
        "favicon.ico",
        RedirectView.as_view(url=f"{settings.STATIC_URL}favicon.ico", permanent=True),
        name="favicon",
    ),
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("courses/", include("apps.courses.urls", namespace="courses")),
    path("learn/<slug:slug>/", include("apps.assignments.urls", namespace="assignments")),
    path("learn/", include("apps.courses.learn_urls", namespace="learn")),
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    path("robots.txt", robots_txt_view, name="robots_txt"),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("styleguide/", styleguide_view, name="styleguide"),
    path("", include("apps.core.urls", namespace="core")),
]

# Custom Error Handlers
handler403 = "apps.core.views.handler403"
handler404 = "apps.core.views.handler404"
handler500 = "apps.core.views.handler500"

# Debug toolbar & media serving in local development
if settings.DEBUG:
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
        ] + urlpatterns

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
