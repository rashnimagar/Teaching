from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadLog,
    DownloadRequest,
    Enrollment,
    Lesson,
    LessonProgress,
    MaterialItem,
)
from apps.courses.services.video import build_safe_video_embed_url, extract_video_info


class LessonAdminForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            "course",
            "title",
            "order",
            "description",
            "video_provider",
            "video_id",
            "video_hash",
            "duration",
            "is_preview",
            "is_published",
        ]

    def clean(self):
        cleaned_data = super().clean()
        vid = cleaned_data.get("video_id")
        provider = cleaned_data.get("video_provider")
        if vid:
            info = extract_video_info(vid, provider)
            cleaned_data["video_id"] = info["video_id"]
            if info.get("provider"):
                cleaned_data["video_provider"] = info["provider"]
            if info.get("video_hash") and not cleaned_data.get("video_hash"):
                cleaned_data["video_hash"] = info["video_hash"]
        return cleaned_data


class LessonInline(admin.TabularInline):
    model = Lesson
    form = LessonAdminForm
    extra = 1
    fields = [
        "order",
        "title",
        "video_provider",
        "video_id",
        "video_hash",
        "duration",
        "is_preview",
        "is_published",
    ]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "slug",
        "is_published",
        "is_featured",
        "is_archived",
        "is_free",
        "price",
        "currency",
        "created_at",
    ]
    list_filter = [
        "is_published",
        "is_featured",
        "is_archived",
        "is_free",
        "currency",
        "requires_approval",
    ]
    search_fields = ["title", "short_description", "description", "slug"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [LessonInline]
    readonly_fields = ["thumbnail_webp", "created_at", "updated_at"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "slug",
                    "short_description",
                    "description",
                    "thumbnail",
                    "thumbnail_webp",
                )
            },
        ),
        (
            _("Visibility & Archival"),
            {"fields": ("is_published", "is_featured", "is_archived", "requires_approval")},
        ),
        (_("Pricing & Monetization"), {"fields": ("is_free", "price", "currency")}),
        (_("Audit Timestamps"), {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    form = LessonAdminForm
    list_display = [
        "title",
        "course",
        "order",
        "video_provider",
        "is_preview",
        "is_published",
        "duration",
    ]
    list_filter = ["course", "video_provider", "is_preview", "is_published"]
    search_fields = ["title", "video_id", "course__title"]
    list_select_related = ["course"]
    autocomplete_fields = ["course"]
    ordering = ["course", "order"]
    readonly_fields = ["embed_preview", "created_at", "updated_at"]
    fields = [
        "course",
        "title",
        "order",
        "description",
        "video_provider",
        "video_id",
        "video_hash",
        "embed_preview",
        "duration",
        "is_preview",
        "is_published",
        "created_at",
        "updated_at",
    ]

    @admin.display(description=_("Video Embed Preview"))
    def embed_preview(self, obj):
        if not obj or not obj.video_id:
            return _("Save with a valid video ID to see an embed preview.")
        try:
            url = build_safe_video_embed_url(obj.video_provider, obj.video_id, obj.video_hash)
            if not url:
                return _("No embed URL available.")
            return format_html(
                '<div style="max-width: 520px; aspect-ratio: 16/9; background: #000; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">'
                '<iframe src="{}" style="width: 100%; height: 100%; border: 0;" '
                'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                'allowfullscreen referrerpolicy="strict-origin-when-cross-origin" '
                'sandbox="allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"></iframe>'
                "</div>",
                url,
            )
        except Exception as e:
            return format_html(
                '<span style="color: #dc2626;">Invalid video configuration: {}</span>', e
            )


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["student", "course", "status", "source", "created_at"]
    list_filter = ["status", "source", "course", "created_at"]
    search_fields = ["student__email", "course__title"]
    list_select_related = ["student", "course"]
    autocomplete_fields = ["student", "course"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ["student", "lesson", "last_position_seconds", "completed_at"]
    list_filter = ["completed_at", "lesson__course"]
    search_fields = ["student__email", "lesson__title", "lesson__course__title"]
    list_select_related = ["student", "lesson", "lesson__course"]
    autocomplete_fields = ["student", "lesson"]
    readonly_fields = ["created_at", "updated_at"]


class MaterialItemInline(admin.StackedInline):
    model = MaterialItem
    extra = 1
    fields = [
        "order",
        "title",
        "item_type",
        "download_policy",
        "file",
        "original_filename",
        "external_url",
        "video_provider",
        "video_id",
        "video_hash",
    ]


@admin.register(CourseMaterial)
class CourseMaterialAdmin(admin.ModelAdmin):
    list_display = ["title", "course", "lesson", "order", "is_published", "is_archived", "created_at"]
    list_filter = ["is_published", "is_archived", "course"]
    search_fields = ["title", "description", "course__title"]
    list_select_related = ["course", "lesson"]
    autocomplete_fields = ["course", "lesson"]
    inlines = [MaterialItemInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MaterialItem)
class MaterialItemAdmin(admin.ModelAdmin):
    list_display = ["title", "material", "item_type", "download_policy", "order", "created_at"]
    list_filter = ["item_type", "download_policy", "material__course"]
    search_fields = ["title", "material__title", "material__course__title"]
    list_select_related = ["material", "material__course"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(DownloadRequest)
class DownloadRequestAdmin(admin.ModelAdmin):
    list_display = [
        "student",
        "material_item",
        "status",
        "requested_at",
        "decided_at",
        "decided_by",
        "expires_at",
    ]
    list_filter = ["status", "requested_at", "material_item__material__course"]
    search_fields = ["student__email", "material_item__title", "teacher_note"]
    list_select_related = ["student", "material_item", "material_item__material", "decided_by"]
    readonly_fields = [
        "student",
        "material_item",
        "status",
        "requested_at",
        "decided_at",
        "decided_by",
        "created_at",
        "updated_at",
    ]
    actions = ["admin_approve_requests", "admin_deny_requests", "admin_revoke_requests"]

    @admin.action(description=_("Approve selected download requests"))
    def admin_approve_requests(self, request, queryset):
        from apps.courses.services.download_requests import transition_download_request

        success_count = 0
        skip_count = 0
        for req in queryset:
            _, ok, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.APPROVED,
                decided_by=request.user,
            )
            if ok:
                success_count += 1
            else:
                skip_count += 1
        self.message_user(
            request,
            f"Approved {success_count} request(s). {skip_count} skipped.",
        )

    @admin.action(description=_("Deny selected download requests"))
    def admin_deny_requests(self, request, queryset):
        from apps.courses.services.download_requests import transition_download_request

        success_count = 0
        skip_count = 0
        for req in queryset:
            _, ok, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.DENIED,
                decided_by=request.user,
                teacher_note="Denied via administrative action.",
            )
            if ok:
                success_count += 1
            else:
                skip_count += 1
        self.message_user(
            request,
            f"Denied {success_count} request(s). {skip_count} skipped.",
        )

    @admin.action(description=_("Revoke selected download requests"))
    def admin_revoke_requests(self, request, queryset):
        from apps.courses.services.download_requests import transition_download_request

        success_count = 0
        skip_count = 0
        for req in queryset:
            _, ok, _ = transition_download_request(
                request_obj=req,
                new_status=DownloadRequest.Status.REVOKED,
                decided_by=request.user,
            )
            if ok:
                success_count += 1
            else:
                skip_count += 1
        self.message_user(
            request,
            f"Revoked {success_count} request(s). {skip_count} skipped.",
        )


@admin.register(DownloadLog)
class DownloadLogAdmin(admin.ModelAdmin):
    list_display = ["student", "material_item", "downloaded_at", "ip_address"]
    list_filter = ["downloaded_at", "material_item__material__course"]
    search_fields = ["student__email", "material_item__title", "ip_address"]
    list_select_related = ["student", "material_item"]
    readonly_fields = ["student", "material_item", "downloaded_at", "ip_address"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
