from django.contrib import admin

from apps.assignments.models import Assignment, Submission


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "course",
        "lesson",
        "opens_at",
        "due_at",
        "max_score",
        "allow_late",
    ]
    list_filter = ["course", "allow_late", "opens_at", "due_at"]
    search_fields = ["title", "instructions", "course__title"]
    list_select_related = ["course", "lesson"]
    autocomplete_fields = ["course", "lesson"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = [
        "assignment",
        "student",
        "submitted_at",
        "is_late",
        "grade",
        "graded_by",
        "graded_at",
    ]
    list_filter = ["is_late", "submitted_at", "graded_at", "assignment__course"]
    search_fields = ["student__email", "assignment__title", "content_text"]
    list_select_related = ["assignment", "student", "graded_by", "assignment__course"]
    autocomplete_fields = ["assignment", "student", "graded_by"]
    readonly_fields = ["submitted_at", "is_late", "created_at", "updated_at"]
