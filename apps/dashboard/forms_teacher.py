import zoneinfo
from datetime import timedelta
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils import timezone
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _

from apps.assignments.models import Assignment, AssignmentAttachment
from apps.core.models import FAQItem, SiteSettings
from apps.core.validators import validate_image_file, validate_safe_url
from apps.courses.models import Course, CourseMaterial, Lesson, MaterialItem
from apps.courses.services.video import extract_video_info
from apps.courses.validators_materials import VIEW_ONLY_ALLOWED_EXTENSIONS, validate_material_file
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
            "short_description": forms.TextInput(
                attrs={"placeholder": "A concise 1-sentence course summary"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Comprehensive syllabus and learning outcomes..."}
            ),
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
            raise ValidationError(
                _("A course with this slug already exists. Please choose a unique slug.")
            )

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

            active_students = self.instance.enrollments.filter(
                status=Enrollment.Status.ACTIVE
            ).count()
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
        help_text=_(
            "Paste a full YouTube, Vimeo, or Bunny Stream video URL, or the raw identifier."
        ),
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        ),
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
            "title": forms.TextInput(
                attrs={"placeholder": "e.g. 01 - Setting Up the Docker Environment"}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Plain-text lesson notes, prerequisites, and instructions...",
                }
            ),
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
        desc = (
            self.cleaned_data.get("description") or self.cleaned_data.get("notes") or ""
        ).strip()
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
                self.add_error(
                    "video_input",
                    _("Could not extract a valid video identifier from the provided URL."),
                )
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
        help_text=_(
            "Check this box if you intentionally want to create or save a closed assignment."
        ),
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
            "title": forms.TextInput(
                attrs={"placeholder": "e.g. Lab 2: Django REST Framework API"}
            ),
            "instructions": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Detailed instructions, rubric, and deliverables...",
                }
            ),
            "max_score": forms.NumberInput(attrs={"min": "1"}),
        }

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)

        # Restrict lesson choice strictly to this course
        if self.course:
            self.fields["lesson"].queryset = Lesson.objects.filter(course=self.course).order_by(
                "order", "id"
            )
            self.fields["lesson"].empty_label = _("None (Course-wide Assignment)")
            self.fields["lesson"].label_from_instance = lambda obj: (
                f"{obj.order}. {obj.title}" + (_(" (Draft)") if not obj.is_published else "")
            )

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
                _("The deadline is in the past. Please check the confirmation box to proceed."),
            )

        # Max score lower-bound protection against existing grades
        if self.instance.pk and max_score is not None:
            highest_grade = self.instance.submissions.filter(grade__isnull=False).aggregate(
                m=Max("grade")
            )["m"]
            if highest_grade is not None and max_score < highest_grade:
                self.add_error(
                    "max_score",
                    _(
                        "Cannot lower maximum score to %(score)s because a student has already received a grade of %(grade)s."
                    )
                    % {"score": max_score, "grade": highest_grade},
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


class TeacherAssignmentAttachmentForm(forms.ModelForm):
    """
    Form for adding, replacing, and editing assignment attachments (handouts, rubrics, starter files).
    Enforces material file validators, size setting, and view-only policy format restrictions.
    """

    file = forms.FileField(
        required=False,
        validators=[validate_material_file],
        label=_("Attachment File"),
        help_text=_(
            "PDF, Office docs (DOCX, PPTX, XLSX), plain text, or images (PNG, JPG) up to 25 MB."
        ),
    )

    class Meta:
        model = AssignmentAttachment
        fields = [
            "title",
            "file",
            "download_policy",
            "is_published",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Lab 2 Starter Code & Handout"}),
            "download_policy": forms.Select(),
        }

    def __init__(self, *args, assignment=None, **kwargs):
        self.assignment = assignment
        super().__init__(*args, **kwargs)
        if not (self.instance and self.instance.pk):
            self.fields["file"].required = True

    def clean_title(self):
        return escape(self.cleaned_data.get("title", "").strip())

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get("file")
        policy = cleaned_data.get("download_policy")

        ext = ""
        if file and hasattr(file, "name"):
            ext = Path(file.name).suffix.lower().lstrip(".")
        elif self.instance and self.instance.pk:
            ext = self.instance.file_extension

        if policy == AssignmentAttachment.DownloadPolicy.VIEW_ONLY:
            if ext and ext not in VIEW_ONLY_ALLOWED_EXTENSIONS:
                raise ValidationError(
                    {
                        "download_policy": _(
                            "View-only mode is supported only for PDF documents and image files (PDF, PNG, JPG)."
                        )
                    }
                )

        return cleaned_data


class TeacherMaterialForm(forms.ModelForm):
    """
    Form for creating and editing CourseMaterial posts.
    Scoped to course, validates linked lesson, plain text escaping.
    """

    class Meta:
        model = CourseMaterial
        fields = [
            "title",
            "lesson",
            "is_published",
            "is_archived",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": "e.g. Week 1 Lecture Slides & Cheatsheets"}
            ),
        }

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)

        if self.course:
            self.fields["lesson"].queryset = Lesson.objects.filter(course=self.course).order_by(
                "order", "id"
            )
            self.fields["lesson"].empty_label = _("None (Course-wide Resource)")
        else:
            self.fields["lesson"].empty_label = _("None (Course-wide Resource)")

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise ValidationError(_("Material title is required."))
        return escape(title)

    def clean_lesson(self):
        lesson = self.cleaned_data.get("lesson")
        if lesson and self.course and lesson.course_id != self.course.id:
            raise ValidationError(_("Selected lesson does not belong to this course."))
        return lesson

    def save(self, commit=True):
        mat = super().save(commit=False)
        if self.course and not mat.course_id:
            mat.course = self.course
        if not mat.pk:
            max_order = (
                CourseMaterial.objects.filter(course=self.course).aggregate(m=Max("order"))["m"]
                or 0
            )
            mat.order = max_order + 1
        if commit:
            mat.save()
        return mat


class TeacherMaterialItemForm(forms.ModelForm):
    """
    Form for creating and editing MaterialItems (file, link, video).
    Enforces safe URLs, video IDs, view-only file types, and detects file replacements.
    """

    file = forms.FileField(
        required=False,
        validators=[validate_material_file],
        label=_("File Upload"),
        help_text=_("PDF, Office documents, plain text, or images up to 25 MB."),
    )

    class Meta:
        model = MaterialItem
        fields = [
            "title",
            "item_type",
            "file",
            "external_url",
            "video_provider",
            "video_id",
            "video_hash",
            "download_policy",
            "is_published",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Architecture Reference Diagram"}),
            "external_url": forms.URLInput(attrs={"placeholder": "https://example.com/docs"}),
            "video_id": forms.TextInput(attrs={"placeholder": "Video ID or full URL"}),
            "video_hash": forms.TextInput(
                attrs={"placeholder": "Optional privacy hash (Bunny/Vimeo)"}
            ),
        }

    def __init__(self, *args, material=None, **kwargs):
        self.material = material
        self.is_replacing_file = False
        super().__init__(*args, **kwargs)
        self.fields["download_policy"].required = False
        self.fields["download_policy"].initial = MaterialItem.DownloadPolicy.REQUEST_REQUIRED
        self.fields["external_url"].required = False
        self.fields["video_id"].required = False

    def clean_title(self):
        return escape(self.cleaned_data.get("title", "").strip())

    def clean_external_url(self):
        val = self.cleaned_data.get("external_url", "").strip()
        if val:
            validate_safe_url(val)
        return val

    def clean(self):
        cleaned_data = super().clean()
        item_type = cleaned_data.get("item_type")
        file = cleaned_data.get("file")
        policy = cleaned_data.get("download_policy")
        if not policy:
            policy = MaterialItem.DownloadPolicy.REQUEST_REQUIRED
            cleaned_data["download_policy"] = policy
        ext_url = cleaned_data.get("external_url")
        vid_id = cleaned_data.get("video_id")

        if item_type == MaterialItem.ItemType.FILE:
            # Must have a file if creating or if existing has none
            if not file and not (self.instance.pk and self.instance.file):
                self.add_error("file", _("A file is required for file items."))

            # Detect replacement
            if self.instance.pk and self.instance.file and file:
                self.is_replacing_file = True

            # If policy is view_only, check extension
            if policy == MaterialItem.DownloadPolicy.VIEW_ONLY:
                check_name = (
                    file.name
                    if file
                    else (
                        self.instance.original_filename
                        or (self.instance.file.name if self.instance.file else "")
                    )
                )
                import os

                ext = os.path.splitext(check_name)[1].lower().lstrip(".")
                if ext not in VIEW_ONLY_ALLOWED_EXTENSIONS:
                    self.add_error(
                        "download_policy",
                        _(
                            "View-only policy is strictly restricted to PDF documents and image files (PNG, JPG)."
                        ),
                    )

        elif item_type == MaterialItem.ItemType.LINK:
            if not ext_url:
                self.add_error("external_url", _("External URL is required for link items."))

        elif item_type == MaterialItem.ItemType.VIDEO:
            if not vid_id:
                self.add_error(
                    "video_id", _("Video identifier or URL is required for video items.")
                )
            else:
                provider = cleaned_data.get("video_provider") or Lesson.VideoProvider.BUNNY
                extracted = extract_video_info(vid_id, provider)
                cleaned_data["video_id"] = extracted["video_id"]
                if extracted.get("provider"):
                    cleaned_data["video_provider"] = extracted["provider"]
                if extracted.get("video_hash") and not cleaned_data.get("video_hash"):
                    cleaned_data["video_hash"] = extracted["video_hash"]

        return cleaned_data

    def save(self, commit=True):
        item = super().save(commit=False)
        if self.material and not item.material_id:
            item.material = self.material
        if not item.pk:
            max_order = (
                MaterialItem.objects.filter(material=self.material).aggregate(m=Max("order"))["m"]
                or 0
            )
            item.order = max_order + 1
        if commit:
            item.save()
        return item


class TeacherSiteSettingsForm(forms.ModelForm):
    """
    Form for editing global SiteSettings in the teacher portal.
    Sanitizes plain text, validates images and social URLs.
    """

    teacher_photo = forms.FileField(
        required=False,
        validators=[validate_image_file],
        label=_("Teacher Photo"),
        help_text=_(
            "Recommended: 800x800 square portrait (PNG/JPG, max 5 MB). WebP is auto-generated."
        ),
    )

    class Meta:
        model = SiteSettings
        fields = [
            "site_name",
            "hero_headline",
            "hero_subheadline",
            "teacher_name",
            "teacher_title",
            "teacher_bio",
            "teacher_photo",
            "contact_email",
            "github_url",
            "twitter_url",
            "linkedin_url",
            "youtube_url",
        ]
        widgets = {
            "site_name": forms.TextInput(attrs={"placeholder": "Teaching Platform"}),
            "hero_headline": forms.TextInput(
                attrs={"placeholder": "Master Skills with Structured Lessons..."}
            ),
            "hero_subheadline": forms.Textarea(attrs={"rows": 3}),
            "teacher_name": forms.TextInput(attrs={"placeholder": "e.g. Rashni Magar"}),
            "teacher_title": forms.TextInput(
                attrs={"placeholder": "e.g. Senior Software Engineer"}
            ),
            "teacher_bio": forms.Textarea(attrs={"rows": 4}),
            "contact_email": forms.EmailInput(attrs={"placeholder": "teacher@example.com"}),
            "github_url": forms.URLInput(attrs={"placeholder": "https://github.com/..."}),
            "twitter_url": forms.URLInput(attrs={"placeholder": "https://x.com/..."}),
            "linkedin_url": forms.URLInput(attrs={"placeholder": "https://linkedin.com/in/..."}),
            "youtube_url": forms.URLInput(attrs={"placeholder": "https://youtube.com/@..."}),
        }

    def clean_site_name(self):
        return escape(self.cleaned_data.get("site_name", "").strip())

    def clean_hero_headline(self):
        return escape(self.cleaned_data.get("hero_headline", "").strip())

    def clean_hero_subheadline(self):
        return escape(self.cleaned_data.get("hero_subheadline", "").strip())

    def clean_teacher_name(self):
        return escape(self.cleaned_data.get("teacher_name", "").strip())

    def clean_teacher_title(self):
        return escape(self.cleaned_data.get("teacher_title", "").strip())

    def clean_teacher_bio(self):
        return escape(self.cleaned_data.get("teacher_bio", "").strip())

    def clean_github_url(self):
        val = self.cleaned_data.get("github_url", "").strip()
        if val:
            validate_safe_url(val)
        return val

    def clean_twitter_url(self):
        val = self.cleaned_data.get("twitter_url", "").strip()
        if val:
            validate_safe_url(val)
        return val

    def clean_linkedin_url(self):
        val = self.cleaned_data.get("linkedin_url", "").strip()
        if val:
            validate_safe_url(val)
        return val

    def clean_youtube_url(self):
        val = self.cleaned_data.get("youtube_url", "").strip()
        if val:
            validate_safe_url(val)
        return val


class TeacherFAQForm(forms.ModelForm):
    """
    Form for creating and editing FAQ items.
    Escapes text, handles order assignment.
    """

    class Meta:
        model = FAQItem
        fields = [
            "question",
            "answer",
            "is_published",
        ]
        widgets = {
            "question": forms.TextInput(
                attrs={"placeholder": "e.g. Can I download lesson materials for offline study?"}
            ),
            "answer": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Detailed answer explaining the policy..."}
            ),
        }

    def clean_question(self):
        return escape(self.cleaned_data.get("question", "").strip())

    def clean_answer(self):
        return escape(self.cleaned_data.get("answer", "").strip())

    def save(self, commit=True):
        faq = super().save(commit=False)
        if not faq.pk:
            max_order = FAQItem.objects.aggregate(m=Max("order"))["m"] or 0
            faq.order = max_order + 1
        if commit:
            faq.save()
        return faq
