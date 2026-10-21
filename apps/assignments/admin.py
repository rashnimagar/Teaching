from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.assignments.models import Assignment, Submission


class SubmissionAdminForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = [
            "assignment",
            "student",
            "content_text",
            "original_filename",
            "file",
            "submitted_at",
            "is_late",
            "grade",
            "feedback",
            "graded_by",
            "graded_at",
        ]

    def clean_grade(self):
        grade = self.cleaned_data.get("grade")
        assignment = getattr(self.instance, "assignment", None)
        if grade is not None:
            if grade < 0:
                raise ValidationError(_("Grade cannot be negative."))
            if assignment and grade > assignment.max_score:
                raise ValidationError(
                    _("Grade cannot exceed maximum score of %(max)s.")
                    % {"max": assignment.max_score}
                )
        return grade


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
    form = SubmissionAdminForm
    list_display = [
        "assignment",
        "student",
        "submitted_at",
        "is_late",
        "file_download_link",
        "grade",
        "graded_by",
        "graded_at",
    ]
    list_filter = [
        "is_late",
        ("grade", admin.EmptyFieldListFilter),
        "assignment__course",
        "submitted_at",
        "graded_at",
    ]
    search_fields = [
        "student__email",
        "student__first_name",
        "student__last_name",
        "assignment__title",
        "content_text",
        "original_filename",
    ]
    list_select_related = ["assignment", "student", "graded_by", "assignment__course"]
    autocomplete_fields = ["assignment", "student", "graded_by"]
    # Requirement 16: student, assignment, file and submitted_at read-only
    readonly_fields = [
        "student",
        "assignment",
        "file",
        "submitted_at",
        "is_late",
        "graded_by",
        "graded_at",
        "file_download_link",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            _("Submission Information"),
            {
                "fields": (
                    "assignment",
                    "student",
                    "submitted_at",
                    "is_late",
                )
            },
        ),
        (
            _("Student Response"),
            {
                "fields": (
                    "content_text",
                    "original_filename",
                    "file",
                    "file_download_link",
                )
            },
        ),
        (
            _("Grading & Feedback"),
            {
                "fields": (
                    "grade",
                    "feedback",
                    "graded_by",
                    "graded_at",
                )
            },
        ),
        (
            _("Metadata"),
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def file_download_link(self, obj):
        """Generates an authenticated download link to the private submission file."""
        if not obj.file:
            return format_html('<span style="color: #9ca3af;">—</span>')
        try:
            download_url = reverse(
                "assignments:download",
                kwargs={"slug": obj.assignment.course.slug, "submission_id": obj.id},
            )
            display_name = obj.original_filename or obj.file.name
            return format_html(
                '<a href="{}" target="_blank" style="font-weight: 600; color: #4f46e5; text-decoration: underline;">Download ({})</a>',
                download_url,
                display_name,
            )
        except Exception:
            return format_html('<span style="color: #ef4444;">Error generating link</span>')

    file_download_link.short_description = _("Download File")

    def save_model(self, request, obj, form, change):
        """
        Requirement 16:
        Set graded_by/graded_at only when the grade changes,
        and clear them if the grade is cleared.
        """
        if "grade" in form.changed_data:
            if obj.grade is not None:
                obj.graded_by = request.user
                obj.graded_at = timezone.now()
            else:
                obj.graded_by = None
                obj.graded_at = None

        super().save_model(request, obj, form, change)
