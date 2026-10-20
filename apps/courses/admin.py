from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.courses.models import Course, Enrollment, Lesson, LessonProgress


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = [
        "order",
        "title",
        "video_provider",
        "video_id",
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
    readonly_fields = ["created_at", "updated_at"]


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
