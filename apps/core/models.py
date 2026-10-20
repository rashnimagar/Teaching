from django.core.cache import cache
from django.db import OperationalError, ProgrammingError, models
from django.utils.translation import gettext_lazy as _

from apps.core.image_utils import generate_webp_variant
from apps.core.validators import validate_image_file


class TimeStampedModel(models.Model):
    """
    An abstract base class model that provides self-updating
    ``created_at`` and ``updated_at`` fields.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SiteSettings(TimeStampedModel):
    """
    Singleton model storing public site branding, hero text, and instructor profile.
    Editable in the Django admin by the teacher without code changes.
    """

    CACHE_KEY = "site_settings_singleton"

    site_name = models.CharField(
        _("site name"),
        max_length=100,
        default="Teaching Platform",
        help_text=_("Public title displayed in navigation, title tags, and structured data."),
    )
    hero_headline = models.CharField(
        _("hero headline"),
        max_length=255,
        default="Master Skills with Structured Lessons & Timed Assignments",
    )
    hero_subheadline = models.TextField(
        _("hero subheadline"),
        default="Focused, distraction-free educational courses designed to build real-world competency.",
    )
    teacher_name = models.CharField(
        _("teacher name"),
        max_length=120,
        blank=True,
        default="",
        help_text=_("Leave blank to hide the instructor section until ready."),
    )
    teacher_title = models.CharField(
        _("teacher title"),
        max_length=150,
        blank=True,
        default="",
        help_text=_("Professional headline or role (e.g. Senior Software Engineer & Instructor)."),
    )
    teacher_bio = models.TextField(
        _("teacher bio"),
        blank=True,
        default="",
        help_text=_("Detailed background narrative. About section is hidden until filled."),
    )
    teacher_photo = models.ImageField(
        _("teacher photo"),
        upload_to="site/teacher/",
        blank=True,
        null=True,
        validators=[validate_image_file],
    )
    teacher_photo_webp = models.ImageField(
        _("teacher photo (WebP variant)"),
        upload_to="site/teacher/webp/",
        blank=True,
        null=True,
    )
    contact_email = models.EmailField(
        _("contact email"),
        blank=True,
        default="",
        help_text=_("Public contact email address displayed in the footer and about section."),
    )
    github_url = models.URLField(_("GitHub URL"), blank=True, default="")
    twitter_url = models.URLField(_("X / Twitter URL"), blank=True, default="")
    linkedin_url = models.URLField(_("LinkedIn URL"), blank=True, default="")
    youtube_url = models.URLField(_("YouTube URL"), blank=True, default="")

    class Meta:
        verbose_name = _("site settings")
        verbose_name_plural = _("site settings")

    def __str__(self):
        return f"{self.site_name} Settings"

    def save(self, *args, **kwargs):
        # Enforce singleton pattern (always primary key 1)
        self.pk = 1
        if not self.created_at and SiteSettings.objects.filter(pk=1).exists():
            self.created_at = (
                SiteSettings.objects.filter(pk=1).values_list("created_at", flat=True).first()
            )

        # Generate resized WebP variant if photo is uploaded
        if self.teacher_photo:
            filename, webp_file = generate_webp_variant(
                self.teacher_photo, max_width=800, max_height=800
            )
            if webp_file:
                self.teacher_photo_webp.save(filename, webp_file, save=False)

        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):
        # Prevent deleting the singleton configuration
        pass

    @classmethod
    def get_solo(cls):
        """
        Retrieve the singleton instance, loading from shared cache if present.
        """
        cached = cache.get(cls.CACHE_KEY)
        if cached is not None:
            return cached

        try:
            obj, _ = cls.objects.get_or_create(
                pk=1,
                defaults={
                    "site_name": "Teaching Platform",
                    "hero_headline": "Master Skills with Structured Lessons & Timed Assignments",
                    "hero_subheadline": "Focused, distraction-free educational courses designed to build real-world competency.",
                },
            )
            cache.set(cls.CACHE_KEY, obj, timeout=3600)
            return obj
        except (OperationalError, ProgrammingError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Database error fetching SiteSettings singleton (%s); returning fallback default.",
                exc,
            )
            return cls(
                site_name="Teaching Platform",
                hero_headline="Master Skills with Structured Lessons & Timed Assignments",
                hero_subheadline="Focused, distraction-free educational courses designed to build real-world competency.",
            )


class FAQItem(TimeStampedModel):
    """
    Frequently asked question item displayed on the home page.
    """

    question = models.CharField(_("question"), max_length=255)
    answer = models.TextField(_("answer"))
    order = models.PositiveIntegerField(_("order"), default=1)
    is_published = models.BooleanField(_("is published"), default=True, db_index=True)

    class Meta:
        verbose_name = _("FAQ item")
        verbose_name_plural = _("FAQ items")
        ordering = ["order", "id"]

    def __str__(self):
        return self.question
