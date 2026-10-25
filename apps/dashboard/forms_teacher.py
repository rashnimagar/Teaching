import zoneinfo
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _

from apps.assignments.models import Assignment
from apps.core.validators import validate_image_file
from apps.courses.models import Course, Lesson
from apps.courses.services.video import extract_video_info
from apps.dashboard.slug_utils import generate_course_slug, validate_ascii_slug

KATHMANDU_TZ = zoneinfo.ZoneInfo("Asia/Kathmandu")


class TeacherCourseForm(forms.ModelForm):
    """
    Form for creating and editing courses in the teacher dashboard.
    Enforces ASCII slug rules, slug locking after publishing/enrollments,
    positive price on paid courses, and plain-text escaping.
    """

    confirm_unpublish = forms.CharField(required=False, widget=forms.HiddenInput)
    thumbnail = forms.FileField(
        required=False,
        validators=[validate_image_file],
        label=_("Course Thumbnail"),
        help_text=_("Recommended: 1200x800 PNG or JPG (max 2 MB). WebP is auto-generated."),
    )

    class Meta:
        model = Course
        fields = [
            "title",
            "slug",
            "short_description",
            "description",
            "thumbnail",
            "is_free",
            "price",
            "currency",
            "is_published",
            "is_featured",
            "requires_approval",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Master Django 5.1 Architecture"}),
            "slug": forms.TextInput(attrs={"placeholder": "e.g. master-django-architecture"}),
            "short_description": forms.TextInput(attrs={"placeholder": "A concise 1-sentence course summary"}),
            "description": forms.Textarea(attrs={"rows": 5, "placeholder": "Comprehensive syllabus and learning outcomes..."}),
            "price": forms.NumberInput(attrs={"placeholder": "0.00", "step": "0.01", "min": "0"}),
            "currency": forms.TextInput(attrs={"placeholder": "NPR", "maxlength": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].required = False
        self.fields["currency"].initial = "NPR"
        # Lock slug if course was already published or has existing enrollments
        self.is_slug_locked = False
        if self.instance.pk:
            if self.instance.is_published or self.instance.enrollments.exists():
                self.is_slug_locked = True
                self.fields["slug"].disabled = True
                self.fields["slug"].help_text = _(
                    "The course slug cannot be changed because this course has already been published or has enrolled students."
                )
            else:
                self.fields["slug"].help_text = _(
                    "URL identifier. Lowercase ASCII letters, numbers, and hyphens only."
                )
        else:
            self.fields["slug"].help_text = _(
                "Leave blank to automatically generate from the course title."
            )

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise ValidationError(_("Course title is required."))
        return escape(title)

    def clean_short_description(self):
        desc = self.cleaned_data.get("short_description", "").strip()
        return escape(desc)

    def clean_description(self):
        desc = self.cleaned_data.get("description", "").strip()
        return escape(desc)

    def clean_slug(self):
        if self.is_slug_locked:
            return self.instance.slug

        raw_slug = self.cleaned_data.get("slug", "").strip()
        title = self.cleaned_data.get("title", "")

        if not raw_slug:
            raw_slug = generate_course_slug(title)

        raw_slug = raw_slug.lower()
        validate_ascii_slug(raw_slug)

        qs = Course.objects.filter(slug=raw_slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_("A course with this slug already exists. Please choose a unique slug."))

        return raw_slug

    def clean(self):
        cleaned_data = super().clean()
        is_free = cleaned_data.get("is_free", True)
        price = cleaned_data.get("price")

        if not cleaned_data.get("currency"):
            cleaned_data["currency"] = "NPR"

        if not is_free:
            if price is None or price <= 0:
                self.add_error("price", _("Paid courses must specify a positive price."))

        # Requirement 3: Unpublishing course with active students requires confirmation
        is_published = cleaned_data.get("is_published", False)
        if self.instance.pk and self.instance.is_published and not is_published:
            from apps.courses.models import Enrollment
            active_students = self.instance.enrollments.filter(status=Enrollment.Status.ACTIVE).count()
            if active_students > 0:
                confirm = cleaned_data.get("confirm_unpublish")
                if confirm != "true":
                    self.add_error(
                        "confirm_unpublish",
                        _(
                            "This course has %(count)s active enrolled student(s) who will lose access. "
                            "Please confirm unpublishing or choose Archive instead."
                        )
                        % {"count": active_students},
                    )

        return cleaned_data


class TeacherLessonForm(forms.ModelForm):
    """
    Form for creating and editing sequential video lessons.
    Requires explicit video provider, accepts full video URLs,
    provides minutes+seconds duration inputs, and resets student
    watch progress positions if the video identifier changes.
    """

    video_input = forms.CharField(
        label=_("Video URL or ID"),
        help_text=_("Paste a full YouTube, Vimeo, or Bunny Stream video URL, or the raw identifier."),
        widget=forms.TextInput(attrs={"placeholder": "e.g. https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
    )
    duration_minutes = forms.IntegerField(
        min_value=0,
        required=False,
        initial=0,
        label=_("Minutes"),
        widget=forms.NumberInput(attrs={"min": "0", "placeholder": "0"}),
    )
    duration_seconds = forms.IntegerField(
        min_value=0,
        max_value=59,
        required=False,
        initial=0,
        label=_("Seconds"),
        widget=forms.NumberInput(attrs={"min": "0", "max": "59", "placeholder": "0"}),
    )

    class Meta:
        model = Lesson
        fields = [
            "title",
            "description",
            "video_provider",
            "is_preview",
            "is_published",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. 01 - Setting Up the Docker Environment"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Plain-text lesson notes, prerequisites, and instructions..."}),
            "video_provider": forms.Select(attrs={"class": "provider-select"}),
        }

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)
        self.fields["video_provider"].empty_label = None  # Provider is strictly required

        if self.instance.pk:
            self.fields["video_input"].initial = self.instance.video_id
            if self.instance.duration:
                total_secs = int(self.instance.duration.total_seconds())
                self.fields["duration_minutes"].initial = total_secs // 60
                self.fields["duration_seconds"].initial = total_secs % 60

    def clean_title(self):
        return escape(self.cleaned_data.get("title", "").strip())

    def clean_description(self):
        desc = (self.cleaned_data.get("description") or self.cleaned_data.get("notes") or "").strip()
        return escape(desc)

    def clean(self):
        cleaned_data = super().clean()
        provider = cleaned_data.get("video_provider")
        raw_video = (cleaned_data.get("video_input") or cleaned_data.get("video_url") or "").strip()

        if not provider:
            self.add_error("video_provider", _("You must explicitly select a video provider."))

        if not raw_video:
            self.add_error("video_input", _("Video URL or identifier is required."))
        elif provider:
            extracted = extract_video_info(raw_video, provider)
            video_id = extracted.get("video_id", "").strip()
            if not video_id:
                self.add_error("video_input", _("Could not extract a valid video identifier from the provided URL."))
            else:
                cleaned_data["video_id"] = video_id
                cleaned_data["video_hash"] = extracted.get("video_hash", "")
                if extracted.get("provider"):
                    cleaned_data["video_provider"] = extracted["provider"]

        # Parse duration
        mins = cleaned_data.get("duration_minutes") or 0
        secs = cleaned_data.get("duration_seconds") or 0
        if mins > 0 or secs > 0:
            cleaned_data["duration"] = timedelta(minutes=mins, seconds=secs)
        else:
            cleaned_data["duration"] = None

        return cleaned_data

    def save(self, commit=True):
        lesson = super().save(commit=False)
        if self.course and not lesson.course_id:
            lesson.course = self.course

        lesson.video_id = self.cleaned_data["video_id"]
        if self.cleaned_data.get("video_hash"):
            lesson.video_hash = self.cleaned_data["video_hash"]
        lesson.video_provider = self.cleaned_data["video_provider"]
        lesson.duration = self.cleaned_data.get("duration")

        if commit:
            lesson.save()
        return lesson


class TeacherAssignmentForm(forms.ModelForm):
    """
    Form for creating and editing course assignments in the teacher dashboard.
    Enforces Asia/Kathmandu time inputs, submission constraints,
    course lesson isolation, and protection against lowering max score below grades.
    """

    opens_at = forms.DateTimeField(
        label=_("Opens At (Asia/Kathmandu)"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "step": "1"}),
        help_text=_("Local time in Nepal (NPT / Asia/Kathmandu)."),
    )
    due_at = forms.DateTimeField(
        label=_("Due At (Asia/Kathmandu)"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "step": "1"}),
        help_text=_("Local time in Nepal (NPT / Asia/Kathmandu)."),
    )
    confirm_unpublish = forms.CharField(required=False, widget=forms.HiddenInput)
    confirm_past_deadline = forms.BooleanField(
        required=False,
        label=_("I confirm this deadline is intentionally set in the past."),
        help_text=_("Check this box if you intentionally want to create or save a closed assignment."),
    )

    class Meta:
        model = Assignment
        fields = [
            "title",
            "instructions",
            "lesson",
            "opens_at",
            "due_at",
            "max_score",
            "allow_late",
            "is_published",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Lab 2: Django REST Framework API"}),
            "instructions": forms.Textarea(attrs={"rows": 6, "placeholder": "Detailed instructions, rubric, and deliverables..."}),
            "max_score": forms.NumberInput(attrs={"min": "1"}),
        }

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)

        # Restrict lesson choice strictly to this course
        if self.course:
            self.fields["lesson"].queryset = Lesson.objects.filter(course=self.course).order_by("order", "id")
            self.fields["lesson"].empty_label = _("None (Course-wide Assignment)")

        # Convert UTC datetimes to Asia/Kathmandu formatted for datetime-local
        if self.instance.pk:
            if self.instance.opens_at:
                local_open = self.instance.opens_at.astimezone(KATHMANDU_TZ)
                self.initial["opens_at"] = local_open.strftime("%Y-%m-%dT%H:%M:%S")
            if self.instance.due_at:
                local_due = self.instance.due_at.astimezone(KATHMANDU_TZ)
                self.initial["due_at"] = local_due.strftime("%Y-%m-%dT%H:%M:%S")

    def clean_title(self):
        return escape(self.cleaned_data.get("title", "").strip())

    def clean_instructions(self):
        return escape(self.cleaned_data.get("instructions", "").strip())

    def clean_lesson(self):
        lesson = self.cleaned_data.get("lesson")
        if lesson and self.course and lesson.course_id != self.course.id:
            raise ValidationError(_("Selected lesson does not belong to this course."))
        return lesson

    def clean(self):
        cleaned_data = super().clean()
        opens_at = cleaned_data.get("opens_at")
        due_at = cleaned_data.get("due_at")
        max_score = cleaned_data.get("max_score")
        confirm_past = cleaned_data.get("confirm_past_deadline", False)

        now = timezone.now()

        # Ensure datetimes are timezone-aware in Kathmandu
        if opens_at and timezone.is_naive(opens_at):
            opens_at = timezone.make_aware(opens_at, KATHMANDU_TZ)
            cleaned_data["opens_at"] = opens_at

        if due_at and timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at, KATHMANDU_TZ)
            cleaned_data["due_at"] = due_at

        # Deadline chronology check
        if opens_at and due_at and due_at <= opens_at:
            self.add_error("due_at", _("Due date must be strictly after the opening date."))

        # Past deadline confirmation
        if due_at and due_at < now and not confirm_past:
            self.add_error(
                "confirm_past_deadline",
                _("The deadline is in the past. Please check the confirmation box to proceed.")
            )

        # Max score lower-bound protection against existing grades
        if self.instance.pk and max_score is not None:
            highest_grade = self.instance.submissions.filter(grade__isnull=False).aggregate(m=Max("grade"))["m"]
            if highest_grade is not None and max_score < highest_grade:
                self.add_error(
                    "max_score",
                    _("Cannot lower maximum score to %(score)s because a student has already received a grade of %(grade)s.")
                    % {"score": max_score, "grade": highest_grade}
                )

        # Requirement 3: Unpublishing assignment with submissions requires confirmation
        is_published = cleaned_data.get("is_published", False)
        if self.instance.pk and self.instance.is_published and not is_published:
            submissions_count = self.instance.submissions.count()
            if submissions_count > 0:
                confirm = cleaned_data.get("confirm_unpublish")
                if confirm != "true":
                    self.add_error(
                        "confirm_unpublish",
                        _(
                            "This assignment has %(count)s submission(s). "
                            "Unpublishing will hide student grades and feedback. Please confirm unpublishing."
                        )
                        % {"count": submissions_count},
                    )

        return cleaned_data

    def save(self, commit=True):
        assignment = super().save(commit=False)
        if self.course and not assignment.course_id:
            assignment.course = self.course
        if commit:
            assignment.save()
        return assignment
