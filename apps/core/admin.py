from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.core.models import FAQItem, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            _("Site Branding & Hero"),
            {
                "fields": (
                    "site_name",
                    "hero_headline",
                    "hero_subheadline",
                )
            },
        ),
        (
            _("Instructor Profile"),
            {
                "description": _(
                    "Leave teacher name and bio blank to hide the instructor section on the home page."
                ),
                "fields": (
                    "teacher_name",
                    "teacher_title",
                    "teacher_bio",
                    "teacher_photo",
                    "teacher_photo_webp",
                    "contact_email",
                ),
            },
        ),
        (
            _("Social Links"),
            {
                "fields": (
                    "github_url",
                    "twitter_url",
                    "linkedin_url",
                    "youtube_url",
                )
            },
        ),
    )
    readonly_fields = ("teacher_photo_webp",)

    def has_add_permission(self, request):
        # Singleton: allow add only if no instance exists yet
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deleting the site settings
        return False


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ("question", "order", "is_published", "updated_at")
    list_editable = ("order", "is_published")
    list_filter = ("is_published",)
    search_fields = ("question", "answer")
    ordering = ("order", "id")
