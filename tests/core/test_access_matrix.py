from contextlib import contextmanager
from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import engines
from django.test import Client
from django.urls import NoReverseMatch, get_resolver, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assignments.models import (
    Assignment,
    AssignmentAttachment,
    AssignmentAttachmentDownload,
    Submission,
    SubmissionEvent,
)
from apps.core.access_matrix import (
    ACCESS_MATRIX,
    ACTORS,
    ENROLLED_OBJECT_STATE_EXPECTATIONS,
    MUTATING_PAYLOAD_FACTORY_EXEMPTIONS,
    POST_RATELIMIT_EXEMPTIONS,
    REMOVED_ALLAUTH_ROUTES,
    VALID_CLASSIFICATIONS,
    format_access_matrix_markdown,
    walk_urlconf,
)
from apps.core.models import FAQItem, SiteSettings
from apps.core.ratelimit import get_view_ratelimit_specs
from apps.courses.models import (
    Course,
    CourseMaterial,
    DownloadLog,
    DownloadRequest,
    Enrollment,
    EnrollmentEvent,
    Lesson,
    LessonProgress,
    MaterialItem,
)
from apps.notifications.models import Notification


def _make_pdf(name: str = "sample.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4\n%EOF\n", content_type="application/pdf")


THIRD_PARTY_TEMPLATE_ROUTES = frozenset(
    {
        "admin_login",
        "admin:login",
        "account_inactive",
        "account_reauthenticate",
        "account_email",
        "account_email_verification_sent",
        "account_change_password",
        "account_set_password",
        "account_reset_password",
        "account_reset_password_done",
        "account_reset_password_from_key",
        "account_reset_password_from_key_done",
        "account_confirm_email",
        "socialaccount_login_cancelled",
        "socialaccount_login_error",
        "socialaccount_signup",
        "socialaccount_connections",
        "google_callback",
    }
)


@contextmanager
def _allow_third_party_template_vars(route_key: str):
    """
    Temporarily disable `InvalidVarSentinel` only when rendering third-party
    `django.contrib.admin` or `django-allauth` built-in templates (which access
    optional dict keys like `attrs.errors` or `cl.formset`), while keeping
    `InvalidVarSentinel` active for all project templates.
    """
    clean_key = route_key.removeprefix("allauth_shadowed:")
    is_third_party = (
        clean_key.startswith("admin:")
        or clean_key.startswith("<unnamed:admin/")
        or clean_key in THIRD_PARTY_TEMPLATE_ROUTES
    )
    django_engine = engines["django"].engine
    old_sentinel = django_engine.string_if_invalid
    if is_third_party:
        django_engine.string_if_invalid = ""
    try:
        yield
    finally:
        django_engine.string_if_invalid = old_sentinel


class _MatrixWorldMixin:
    """Shared fixtures and URL resolution helpers for matrix and regression tests."""

    @pytest.fixture(autouse=True)
    def setup_matrix_world(self):
        self.password = "TestPassword123!"

        # Actors
        self.student_unenrolled = User.objects.create_user(
            email="unenrolled@example.com",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.student_pending = User.objects.create_user(
            email="pending@example.com",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.student_revoked = User.objects.create_user(
            email="revoked@example.com",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.student_active = User.objects.create_user(
            email="active@example.com",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.student_other_course = User.objects.create_user(
            email="other_course@example.com",
            password=self.password,
            role=User.Role.STUDENT,
        )
        self.teacher = User.objects.create_user(
            email="teacher@example.com",
            password=self.password,
            role=User.Role.TEACHER,
            is_staff=True,
        )
        self.teacher_non_staff = User.objects.create_user(
            email="teacher_nonstaff@example.com",
            password=self.password,
            role=User.Role.TEACHER,
            is_staff=False,
        )
        self.superuser = User.objects.create_superuser(
            email="superuser@example.com",
            password=self.password,
        )

        # Primary course & other course
        self.course = Course.objects.create(
            title="Primary Matrix Course",
            slug="primary-matrix-course",
            short_description="Primary course",
            description="Detailed description",
            is_published=True,
        )
        self.other_course = Course.objects.create(
            title="Other Matrix Course",
            slug="other-matrix-course",
            short_description="Other course",
            description="Other description",
            is_published=True,
        )

        # Enrollments
        self.pending_enrollment = Enrollment.objects.create(
            student=self.student_pending,
            course=self.course,
            status=Enrollment.Status.PENDING,
        )
        self.revoked_enrollment = Enrollment.objects.create(
            student=self.student_revoked,
            course=self.course,
            status=Enrollment.Status.REVOKED,
        )
        self.active_enrollment = Enrollment.objects.create(
            student=self.student_active,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        self.other_enrollment = Enrollment.objects.create(
            student=self.student_other_course,
            course=self.other_course,
            status=Enrollment.Status.ACTIVE,
        )
        self.enrollment_event = EnrollmentEvent.objects.create(
            enrollment=self.active_enrollment,
            actor=self.teacher,
            from_status=Enrollment.Status.PENDING,
            to_status=Enrollment.Status.ACTIVE,
        )

        # Lessons
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="Primary Lesson 1",
            order=1,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
            is_published=True,
        )
        self.other_lesson = Lesson.objects.create(
            course=self.other_course,
            title="Other Lesson 1",
            order=1,
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="dQw4w9WgXcQ",
            is_published=True,
        )
        self.lesson_progress = LessonProgress.objects.create(
            student=self.student_active,
            lesson=self.lesson,
        )

        # Course Materials & Items
        self.material = CourseMaterial.objects.create(
            course=self.course,
            title="Primary Material Container",
            order=1,
            is_published=True,
        )
        self.other_material = CourseMaterial.objects.create(
            course=self.other_course,
            title="Other Material Container",
            order=1,
            is_published=True,
        )
        self.material_item = MaterialItem.objects.create(
            material=self.material,
            title="Primary PDF Handout",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
            file=_make_pdf("primary_handout.pdf"),
            order=1,
            is_published=True,
        )
        self.other_material_item = MaterialItem.objects.create(
            material=self.other_material,
            title="Other PDF Handout",
            item_type=MaterialItem.ItemType.FILE,
            download_policy=MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
            file=_make_pdf("other_handout.pdf"),
            order=1,
            is_published=True,
        )
        # Approved download request for student_active so download/preview returns 200
        self.download_request = DownloadRequest.objects.create(
            student=self.student_active,
            material_item=self.material_item,
            status=DownloadRequest.Status.APPROVED,
            decided_by=self.teacher,
            decided_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.download_log = DownloadLog.objects.create(
            student=self.student_active,
            material_item=self.material_item,
            ip_address="127.0.0.1",
        )

        # Assignments, Attachments & Submissions
        now = timezone.now()
        self.assignment = Assignment.objects.create(
            course=self.course,
            lesson=self.lesson,
            title="Primary Assignment 1",
            instructions="Complete all questions.",
            opens_at=now - timedelta(days=2),
            due_at=now + timedelta(days=5),
            max_score=100,
            is_published=True,
        )
        self.other_assignment = Assignment.objects.create(
            course=self.other_course,
            lesson=self.other_lesson,
            title="Other Assignment 1",
            instructions="Complete other questions.",
            opens_at=now - timedelta(days=2),
            due_at=now + timedelta(days=5),
            max_score=100,
            is_published=True,
        )
        self.attachment = AssignmentAttachment.objects.create(
            assignment=self.assignment,
            title="Primary Worksheet PDF",
            file=_make_pdf("worksheet.pdf"),
            order=1,
            is_published=True,
        )
        self.attachment_download = AssignmentAttachmentDownload.objects.create(
            attachment=self.attachment,
            student=self.student_active,
        )
        self.other_attachment = AssignmentAttachment.objects.create(
            assignment=self.other_assignment,
            title="Other Worksheet PDF",
            file=_make_pdf("other_worksheet.pdf"),
            order=1,
            is_published=True,
        )
        self.submission = Submission.objects.create(
            assignment=self.assignment,
            student=self.student_active,
            content_text="Initial submission text.",
            file=_make_pdf("student_sub.pdf"),
            original_filename="student_sub.pdf",
            file_size=18,
            is_unlocked=True,
        )
        self.other_submission = Submission.objects.create(
            assignment=self.other_assignment,
            student=self.student_other_course,
            content_text="Other course submission.",
            file=_make_pdf("other_sub.pdf"),
            original_filename="other_sub.pdf",
            file_size=18,
        )
        self.submission_event = SubmissionEvent.objects.create(
            submission=self.submission,
            actor=self.teacher,
            action="graded",
        )

        # Core & Admin models
        self.site_settings = SiteSettings.get_solo()
        self.faq = FAQItem.objects.create(
            question="How does grading work?",
            answer="Teachers grade submissions in the dashboard.",
            order=1,
            is_published=True,
        )
        self.group = Group.objects.create(name="TestMatrixGroup")
        self.email_address = EmailAddress.objects.create(
            user=self.student_active,
            email=self.student_active.email,
            verified=True,
            primary=True,
        )
        self.unverified_email = EmailAddress.objects.create(
            user=self.student_unenrolled,
            email=self.student_unenrolled.email,
            verified=False,
            primary=True,
        )
        self.social_app = SocialApp.objects.create(
            provider="google",
            name="Google Matrix Test",
            client_id="matrix-client-id",
            secret="matrix-secret",
        )
        self.social_account = SocialAccount.objects.create(
            user=self.student_active,
            provider="google",
            uid="google-uid-12345",
        )
        self.social_token = SocialToken.objects.create(
            app=self.social_app,
            account=self.social_account,
            token="matrix-oauth-token",
        )

        # Create a notification for every authenticated actor so notifications:mark_read works for each
        self.notifications_by_user = {}
        for user in (
            self.student_unenrolled,
            self.student_pending,
            self.student_revoked,
            self.student_active,
            self.student_other_course,
            self.teacher,
            self.teacher_non_staff,
            self.superuser,
        ):
            self.notifications_by_user[user.id] = Notification.objects.create(
                recipient=user,
                kind=Notification.Kind.ENROLLMENT_APPROVED,
                title="Matrix Test Notification",
                body="Hello from matrix test.",
            )

        self.admin_model_pks = {
            ("auth", "group"): self.group.pk,
            ("account", "emailaddress"): self.email_address.pk,
            ("socialaccount", "socialapp"): self.social_app.pk,
            ("socialaccount", "socialtoken"): self.social_token.pk,
            ("socialaccount", "socialaccount"): self.social_account.pk,
            ("core", "sitesettings"): self.site_settings.pk,
            ("core", "faqitem"): self.faq.pk,
            ("accounts", "user"): self.student_active.pk,
            ("courses", "course"): self.course.pk,
            ("courses", "lesson"): self.lesson.pk,
            ("courses", "enrollment"): self.active_enrollment.pk,
            ("courses", "enrollmentevent"): self.enrollment_event.pk,
            ("courses", "lessonprogress"): self.lesson_progress.pk,
            ("courses", "coursematerial"): self.material.pk,
            ("courses", "materialitem"): self.material_item.pk,
            ("courses", "downloadrequest"): self.download_request.pk,
            ("courses", "downloadlog"): self.download_log.pk,
            ("assignments", "assignment"): self.assignment.pk,
            ("assignments", "submission"): self.submission.pk,
            ("assignments", "submissionevent"): self.submission_event.pk,
        }

    def _resolve_route_url(self, route_key: str, actor_user=None, entry: dict | None = None) -> str:
        """
        Resolve any route in `ACCESS_MATRIX` using `reverse()` names (never typed paths).
        For unnamed third-party patterns in Django admin / allauth, derives the URL via
        `reverse()` on the sibling named route or `get_resolver().reverse(callback)`.
        """
        url_name = route_key.removeprefix("allauth_shadowed:")

        # Handle unnamed third-party patterns via reverse() on their named counterparts or callbacks
        if url_name.startswith("<unnamed:"):
            if url_name == "<unnamed:admin/(?P<url>.*)$>":
                return f"{reverse('admin:index')}nonexistent-admin-path/"
            if url_name.startswith("<unnamed:admin/"):
                # Format: <unnamed:admin/{app}/{model}/<path:object_id>/>
                inner = url_name.removeprefix("<unnamed:admin/").removesuffix("/<path:object_id>/>")
                app_label, model_name = inner.split("/", 1)
                pk = self.admin_model_pks[(app_label, model_name)]
                change_url = reverse(f"admin:{app_label}_{model_name}_change", args=[pk])
                return change_url.removesuffix("change/")
            # Unnamed allauth legacy RedirectView patterns: reverse via callback in URLResolver
            if entry is not None:
                rel = get_resolver("config.urls").reverse(entry["callback"])
                return f"/{rel.lstrip('/')}"

        # Admin model routes
        for (app_label, model_name), pk in self.admin_model_pks.items():
            prefix = f"admin:{app_label}_{model_name}_"
            if url_name.startswith(prefix):
                suffix = url_name.removeprefix(prefix)
                if suffix in ("changelist", "add"):
                    return reverse(url_name)
                return reverse(url_name, args=[pk])

        if url_name == "admin:app_list":
            return reverse("admin:app_list", kwargs={"app_label": "courses"})
        if url_name == "admin:view_on_site":
            ct = ContentType.objects.get_for_model(Course)
            return reverse(
                "admin:view_on_site",
                kwargs={"content_type_id": ct.pk, "object_id": self.course.pk},
            )
        if url_name == "admin:auth_user_password_change":
            return reverse("admin:auth_user_password_change", args=[self.student_active.pk])

        # Allauth parameterized routes
        if url_name == "account_confirm_email":
            if self.unverified_email.verified:
                self.unverified_email.verified = False
                self.unverified_email.save(update_fields=["verified"])
            key = EmailConfirmationHMAC(self.unverified_email).key
            return reverse("account_confirm_email", args=[key])
        if url_name == "account_reset_password_from_key":
            return reverse(
                "account_reset_password_from_key",
                kwargs={"uidb36": "1", "key": "set-password"},
            )

        # Notifications
        if url_name == "notifications:mark_read":
            notif_user = actor_user or self.student_active
            notif = self.notifications_by_user[notif_user.id]
            return reverse("notifications:mark_read", kwargs={"notification_id": notif.id})

        # Courses & Learn routes
        if url_name in ("courses:detail", "courses:enroll"):
            return reverse(url_name, kwargs={"slug": self.course.slug})
        if url_name in ("learn:course", "learn:materials"):
            return reverse(url_name, kwargs={"course_slug": self.course.slug})
        if url_name in ("learn:lesson", "learn:toggle_complete", "learn:playback_position"):
            return reverse(
                url_name,
                kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
            )
        if url_name in (
            "learn:material_request",
            "learn:material_cancel",
            "learn:material_download",
            "learn:material_preview",
        ):
            return reverse(
                url_name,
                kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
            )

        # Assignments routes
        if url_name == "assignments:list":
            return reverse(url_name, kwargs={"slug": self.course.slug})
        if url_name == "assignments:detail":
            return reverse(
                url_name,
                kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
            )
        if url_name == "assignments:download":
            return reverse(
                url_name,
                kwargs={"slug": self.course.slug, "submission_id": self.submission.id},
            )
        if url_name in ("assignments:attachment_download", "assignments:attachment_preview"):
            return reverse(
                url_name,
                kwargs={"slug": self.course.slug, "attachment_id": self.attachment.id},
            )

        # Dashboard routes with parameters
        if url_name == "dashboard:teacher_permission_action":
            return reverse(url_name, kwargs={"request_id": self.download_request.id})
        if url_name in ("dashboard:teacher_approve_for_all", "dashboard:teacher_download_history"):
            return reverse(url_name, kwargs={"item_id": self.material_item.id})
        if url_name in (
            "dashboard:teacher_course_edit",
            "dashboard:teacher_course_archive",
            "dashboard:teacher_lessons",
            "dashboard:teacher_course_lessons",
            "dashboard:teacher_lesson_create",
            "dashboard:teacher_course_lesson_create",
            "dashboard:teacher_assignments",
            "dashboard:teacher_course_assignments",
            "dashboard:teacher_assignment_create",
            "dashboard:teacher_course_assignment_create",
            "dashboard:teacher_course_grades_export",
            "dashboard:teacher_course_progress_export",
            "dashboard:teacher_course_materials",
            "dashboard:teacher_material_create",
        ):
            return reverse(url_name, kwargs={"slug": self.course.slug})
        if url_name in (
            "dashboard:teacher_lesson_edit",
            "dashboard:teacher_course_lesson_edit",
            "dashboard:teacher_lesson_toggle_publish",
            "dashboard:teacher_course_lesson_toggle_publish",
            "dashboard:teacher_lesson_reorder",
            "dashboard:teacher_course_lesson_reorder",
            "dashboard:teacher_lesson_delete",
            "dashboard:teacher_course_lesson_delete",
        ):
            return reverse(
                url_name,
                kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
            )
        if url_name in (
            "dashboard:teacher_assignment_edit",
            "dashboard:teacher_course_assignment_edit",
            "dashboard:teacher_assignment_toggle_publish",
            "dashboard:teacher_course_assignment_toggle_publish",
            "dashboard:teacher_assignment_delete",
            "dashboard:teacher_course_assignment_delete",
            "dashboard:teacher_assignment_attachment_add",
            "dashboard:teacher_course_assignment_submissions",
            "dashboard:teacher_missed_deadlines",
        ):
            return reverse(
                url_name,
                kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
            )
        if url_name in (
            "dashboard:teacher_assignment_attachment_edit",
            "dashboard:teacher_assignment_attachment_toggle_publish",
            "dashboard:teacher_assignment_attachment_reorder",
            "dashboard:teacher_assignment_attachment_delete",
            "dashboard:teacher_assignment_attachment_downloads",
        ):
            return reverse(
                url_name,
                kwargs={
                    "slug": self.course.slug,
                    "assignment_id": self.assignment.id,
                    "attachment_id": self.attachment.id,
                },
            )
        if url_name == "dashboard:teacher_enrollment_action":
            return reverse(url_name, kwargs={"enrollment_id": self.pending_enrollment.id})
        if url_name in (
            "dashboard:teacher_submission_grade",
            "dashboard:teacher_submission_unlock",
        ):
            return reverse(url_name, kwargs={"submission_id": self.submission.id})
        if url_name in (
            "dashboard:teacher_student_detail",
            "dashboard:teacher_student_toggle_active",
        ):
            return reverse(url_name, kwargs={"student_id": self.student_active.id})
        if url_name in (
            "dashboard:teacher_material_edit",
            "dashboard:teacher_material_toggle_publish",
            "dashboard:teacher_material_archive",
            "dashboard:teacher_material_delete",
            "dashboard:teacher_material_item_create",
        ):
            return reverse(
                url_name,
                kwargs={"slug": self.course.slug, "material_id": self.material.id},
            )
        if url_name in (
            "dashboard:teacher_material_item_edit",
            "dashboard:teacher_material_item_toggle_publish",
            "dashboard:teacher_material_item_delete",
            "dashboard:teacher_material_item_reorder",
            "dashboard:teacher_material_item_policy",
            "dashboard:teacher_material_item_history",
        ):
            return reverse(
                url_name,
                kwargs={
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.material_item.id,
                },
            )
        if url_name in (
            "dashboard:teacher_faq_edit",
            "dashboard:teacher_faq_toggle_publish",
            "dashboard:teacher_faq_reorder",
            "dashboard:teacher_faq_delete",
        ):
            return reverse(url_name, kwargs={"faq_id": self.faq.id})

        return reverse(url_name)


@pytest.mark.django_db
class TestUrlAccessMatrix(_MatrixWorldMixin):
    """
    Phase 8B-1 URL Access Matrix & Authorization Audit Suite.
    """

    def test_every_production_route_is_classified_in_access_matrix(self):
        """
        Walk `config.urls` (the production URLconf) and require every discovered route
        to be present in `ACCESS_MATRIX` with a valid classification.
        """
        discovered = walk_urlconf("config.urls")
        discovered_keys = {entry["route_key"] for entry in discovered}
        registered_keys = set(ACCESS_MATRIX.keys())

        unclassified = sorted(discovered_keys - registered_keys)
        assert not unclassified, (
            f"Unclassified routes found in config.urls: {unclassified}. "
            "Every route MUST be explicitly classified in apps/core/access_matrix.py (ACCESS_MATRIX) "
            "as one of: public, authenticated, enrolled, teacher, superuser, or test-only."
        )

        stale = sorted(registered_keys - discovered_keys)
        assert not stale, (
            f"Stale route entries in ACCESS_MATRIX not present in config.urls: {stale}."
        )

        for route_key, spec in ACCESS_MATRIX.items():
            assert spec.classification in VALID_CLASSIFICATIONS, (
                f"Route {route_key} has invalid classification {spec.classification!r}."
            )
            if spec.actor_overrides:
                assert spec.exception_reason.strip(), (
                    f"Route {route_key} defines actor_overrides without a written exception_reason."
                )

        # Ensure markdown formatter produces non-empty output containing all routes
        md_table = format_access_matrix_markdown()
        assert "| `core:home` |" in md_table
        assert "| `dashboard:teacher` |" in md_table

    def test_test_only_error_routes_are_absent_from_production_urlconf(self):
        """
        Confirm that the test-only error simulation routes (`error_403`, `error_404`, `error_500`)
        in `config.urls_test` are completely absent from the production URLconf (`config.urls`).
        """
        discovered = walk_urlconf("config.urls")
        discovered_names = {entry["url_name"] for entry in discovered}
        for test_route in ("error_403", "error_404", "error_500"):
            assert test_route not in discovered_names, (
                f"Test-only route {test_route!r} must NOT be present in production config.urls!"
            )
            with pytest.raises(NoReverseMatch):
                reverse(test_route, urlconf="config.urls")

    def test_ratelimit_specs_match_registry_and_all_post_routes_are_covered(self):
        """
        Compare `view.ratelimit_spec` recorded by `@track_ratelimit` with `spec.ratelimit`
        in `ACCESS_MATRIX`, and fail if any POST-capable view has no rate limit and is not
        on `POST_RATELIMIT_EXEMPTIONS` with a non-empty reason.
        """
        discovered = walk_urlconf("config.urls")
        for entry in discovered:
            route_key = entry["route_key"]
            spec = ACCESS_MATRIX[route_key]
            view_specs = get_view_ratelimit_specs(entry["callback"])
            actual_ratelimit = (
                ",".join(f"{s['key']}:{s['rate']}" for s in view_specs) if view_specs else None
            )
            assert actual_ratelimit == spec.ratelimit, (
                f"Rate limit mismatch on {route_key}: view decorator has {actual_ratelimit!r}, "
                f"but ACCESS_MATRIX has {spec.ratelimit!r}."
            )

            if "POST" in spec.methods and not spec.ratelimit:
                assert route_key in POST_RATELIMIT_EXEMPTIONS, (
                    f"POST-capable route {route_key!r} has no @track_ratelimit decorator and is not "
                    "listed in POST_RATELIMIT_EXEMPTIONS with a justification."
                )
                assert POST_RATELIMIT_EXEMPTIONS[route_key].strip(), (
                    f"POST_RATELIMIT_EXEMPTIONS[{route_key!r}] must have a non-empty reason."
                )

    def test_all_routes_enforce_expected_response_for_every_actor(self):
        """
        Test every route in `config.urls` across all 8 actors:
        guest, student_unenrolled, student_pending, student_revoked,
        student_active, student_other_course, teacher, superuser.
        """
        discovered = walk_urlconf("config.urls")
        actor_users = {
            "guest": None,
            "student_unenrolled": self.student_unenrolled,
            "student_pending": self.student_pending,
            "student_revoked": self.student_revoked,
            "student_active": self.student_active,
            "student_other_course": self.student_other_course,
            "teacher": self.teacher,
            "superuser": self.superuser,
        }
        assert set(actor_users.keys()) == set(ACTORS)

        clients = {}
        for actor_name, user in actor_users.items():
            c = Client()
            if user is not None:
                c.force_login(user)
            clients[actor_name] = c

        failures = []
        for entry in discovered:
            route_key = entry["route_key"]
            spec = ACCESS_MATRIX[route_key]
            method = "GET" if "GET" in spec.methods else "POST"

            for actor_name, actor_user in actor_users.items():
                url = self._resolve_route_url(route_key, actor_user=actor_user, entry=entry)
                client_obj = clients[actor_name]
                with _allow_third_party_template_vars(route_key):
                    if method == "GET":
                        resp = client_obj.get(url, REMOTE_ADDR="127.0.0.1")
                    else:
                        post_data = (
                            {"position": "42"} if route_key == "learn:playback_position" else {}
                        )
                        resp = client_obj.post(url, post_data, REMOTE_ADDR="127.0.0.1")

                # Re-authenticate if any route (e.g. logout, confirm_email, reset_password_from_key) logged the actor out
                if actor_user is not None and "_auth_user_id" not in client_obj.session:
                    client_obj.force_login(actor_user)
                # Ensure student_unenrolled and student_other_course stay unenrolled in self.course if courses:enroll enrolled them
                if route_key == "courses:enroll":
                    Enrollment.objects.filter(
                        course=self.course,
                        student__in=[self.student_unenrolled, self.student_other_course],
                    ).delete()
                # Ensure student_active remains active if teacher_student_toggle_active toggled it
                if route_key == "dashboard:teacher_student_toggle_active":
                    self.student_active.is_active = True
                    self.student_active.save(update_fields=["is_active"])
                # Ensure course remains published/unarchived if teacher_course_archive toggled it
                if route_key == "dashboard:teacher_course_archive":
                    self.course.is_published = True
                    self.course.is_archived = False
                    self.course.save(update_fields=["is_published", "is_archived"])
                # Ensure lesson/assignment/attachment/material/item/faq stay published and exist
                if "toggle_publish" in route_key or "archive" in route_key or "delete" in route_key:
                    Lesson.objects.filter(pk=self.lesson.pk).update(is_published=True)
                    Assignment.objects.filter(pk=self.assignment.pk).update(is_published=True)
                    AssignmentAttachment.objects.filter(pk=self.attachment.pk).update(
                        is_published=True
                    )
                    CourseMaterial.objects.filter(pk=self.material.pk).update(
                        is_published=True, is_archived=False
                    )
                    MaterialItem.objects.filter(pk=self.material_item.pk).update(
                        is_published=True,
                        download_policy=MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
                    )
                    if not FAQItem.objects.filter(pk=self.faq.pk).exists():
                        self.faq = FAQItem.objects.create(
                            id=self.faq.id,
                            question="How does grading work?",
                            answer="Teachers grade submissions in the dashboard.",
                            order=1,
                            is_published=True,
                        )
                    else:
                        FAQItem.objects.filter(pk=self.faq.pk).update(is_published=True)

                expected_code = spec.expected_for_actor(actor_name, method=method)
                assert isinstance(expected_code, int)
                if resp.status_code != expected_code:
                    failures.append(
                        f"{route_key} [{method}] actor={actor_name}: got {resp.status_code}, "
                        f"expected {expected_code} (class={spec.classification})"
                    )

            # Also verify every named CaseVariantSpec (e.g., ajax_post, cancelled_oauth, valid_query)
            for variant in spec.case_variants:
                for actor_name, actor_user in actor_users.items():
                    url = self._resolve_route_url(route_key, actor_user=actor_user, entry=entry)
                    client_obj = clients[actor_name]
                    with _allow_third_party_template_vars(route_key):
                        if variant.method == "GET":
                            v_resp = client_obj.get(
                                url,
                                data=variant.query_params,
                                REMOTE_ADDR="127.0.0.1",
                                **variant.headers,
                            )
                        else:
                            v_resp = client_obj.post(
                                url,
                                data=variant.query_params,
                                REMOTE_ADDR="127.0.0.1",
                                **variant.headers,
                            )
                    if actor_user is not None and "_auth_user_id" not in client_obj.session:
                        client_obj.force_login(actor_user)
                    if "toggle_publish" in route_key:
                        Lesson.objects.filter(pk=self.lesson.pk).update(is_published=True)
                        Assignment.objects.filter(pk=self.assignment.pk).update(is_published=True)
                    expected_v_code = variant.actor_expectations[actor_name]
                    if v_resp.status_code != expected_v_code:
                        failures.append(
                            f"{route_key} [{variant.name}:{variant.method}] actor={actor_name}: "
                            f"got {v_resp.status_code}, expected {expected_v_code}"
                        )

        assert not failures, "Access matrix actor expectations failed:\n" + "\n".join(failures)

    def test_unified_is_teacher_user_allows_teacher_role_without_is_staff(self):
        """
        Verify that a teacher with `role=User.Role.TEACHER` and `is_staff=False` is treated
        identically to a staff teacher across all application routes (courses, learn,
        assignments, dashboard).
        """
        c = Client()
        c.force_login(self.teacher_non_staff)
        for route_key in (
            "dashboard:teacher",
            "dashboard:teacher_courses",
            "dashboard:teacher_permissions",
            "dashboard:teacher_enrollments",
            "dashboard:teacher_submissions",
            "dashboard:teacher_students",
            "dashboard:teacher_materials",
            "dashboard:teacher_settings",
            "dashboard:teacher_faqs",
            "learn:lesson",
            "learn:materials",
            "learn:material_download",
            "learn:material_preview",
            "assignments:list",
            "assignments:detail",
            "assignments:download",
            "assignments:attachment_download",
            "assignments:attachment_preview",
        ):
            url = self._resolve_route_url(route_key, actor_user=self.teacher_non_staff)
            resp = c.get(url)
            expected = ACCESS_MATRIX[route_key].expected_for_actor("teacher", method="GET")
            assert resp.status_code == expected, (
                f"Teacher with is_staff=False failed on {route_key}: got {resp.status_code}, expected {expected}"
            )

    def test_mutating_routes_method_csrf_role_and_payload_factories(self):
        """
        For every mutating route (anything accepting POST):
        1. If POST-only, GET returns 405.
        2. POST without a CSRF token returns 403.
        3. POST by the wrong role is refused (302 or 403).
        4. Every mutating route has an explicit payload factory (or is in
           `MUTATING_PAYLOAD_FACTORY_EXEMPTIONS` with a reason — no silent skips),
           and POST by the authorized role with that payload succeeds (200 or 302).
        """
        mutating_keys = [
            route_key
            for route_key, spec in ACCESS_MATRIX.items()
            if "POST" in spec.methods and not route_key.startswith("allauth_shadowed:")
        ]

        def _build_disposable_lesson():
            return Lesson.objects.create(
                course=self.course,
                title="Disposable Lesson",
                order=99,
                video_provider=Lesson.VideoProvider.YOUTUBE,
                video_id="dQw4w9WgXcQ",
                is_published=True,
            )

        def _build_disposable_assignment():
            now = timezone.now()
            return Assignment.objects.create(
                course=self.course,
                title="Disposable Assignment",
                instructions="Delete me",
                opens_at=now - timedelta(days=1),
                due_at=now + timedelta(days=5),
                is_published=True,
            )

        def _build_disposable_attachment():
            return AssignmentAttachment.objects.create(
                assignment=self.assignment,
                title="Disposable Attachment",
                file=_make_pdf("disp.pdf"),
                order=99,
                is_published=True,
            )

        def _build_disposable_material():
            return CourseMaterial.objects.create(
                course=self.course,
                title="Disposable Material",
                order=99,
                is_published=True,
            )

        def _build_disposable_material_item():
            return MaterialItem.objects.create(
                material=self.material,
                title="Disposable Item",
                item_type=MaterialItem.ItemType.LINK,
                external_url="https://example.com",
                order=99,
                is_published=True,
            )

        def _build_disposable_faq():
            return FAQItem.objects.create(
                question="Disposable FAQ?",
                answer="Yes.",
                order=99,
                is_published=True,
            )

        # Map every non-exempt mutating route to (actor_user, url_callable, payload_callable)
        payload_factories = {
            "account_login": (
                None,
                lambda: reverse("account_login"),
                lambda: {"login": self.student_active.email, "password": self.password},
            ),
            "account_signup": (
                None,
                lambda: reverse("account_signup"),
                lambda: {
                    "email": "fresh_signup_student@example.com",
                    "password1": "VeryStrongPass123!@#",
                    "password2": "VeryStrongPass123!@#",
                },
            ),
            "google_login": (
                None,
                lambda: reverse("google_login"),
                lambda: {},
            ),
            "account_logout": (
                self.student_active,
                lambda: reverse("account_logout"),
                lambda: {},
            ),
            "account_change_password": (
                self.student_active,
                lambda: reverse("account_change_password"),
                lambda: {
                    "oldpassword": self.password,
                    "password1": self.password,
                    "password2": self.password,
                },
            ),
            "account_reset_password": (
                None,
                lambda: reverse("account_reset_password"),
                lambda: {"email": self.student_active.email},
            ),
            "account_reset_password_from_key": (
                None,
                lambda: reverse(
                    "account_reset_password_from_key",
                    kwargs={"uidb36": "1", "key": "set-password"},
                ),
                lambda: {
                    "password1": self.password,
                    "password2": self.password,
                },
            ),
            "account_confirm_email": (
                None,
                lambda: (
                    EmailAddress.objects.filter(pk=self.unverified_email.pk).update(verified=False),
                    reverse(
                        "account_confirm_email",
                        args=[EmailConfirmationHMAC(self.unverified_email).key],
                    ),
                )[1],
                lambda: {},
            ),
            "courses:enroll": (
                self.student_unenrolled,
                lambda: reverse("courses:enroll", kwargs={"slug": self.course.slug}),
                lambda: {},
            ),
            "learn:toggle_complete": (
                self.student_active,
                lambda: reverse(
                    "learn:toggle_complete",
                    kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {},
            ),
            "learn:playback_position": (
                self.student_active,
                lambda: reverse(
                    "learn:playback_position",
                    kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {"position": "42"},
            ),
            "learn:material_request": (
                self.student_active,
                lambda: reverse(
                    "learn:material_request",
                    kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
                ),
                lambda: {"request_note": "Please approve"},
            ),
            "learn:material_cancel": (
                self.student_active,
                lambda: reverse(
                    "learn:material_cancel",
                    kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
                ),
                lambda: {},
            ),
            "assignments:detail": (
                self.student_active,
                lambda: reverse(
                    "assignments:detail",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                ),
                lambda: {"content_text": "Valid student submission payload."},
            ),
            "notifications:mark_read": (
                self.student_active,
                lambda: reverse(
                    "notifications:mark_read",
                    kwargs={
                        "notification_id": self.notifications_by_user[self.student_active.id].id
                    },
                ),
                lambda: {},
            ),
            "notifications:mark_all_read": (
                self.student_active,
                lambda: reverse("notifications:mark_all_read"),
                lambda: {},
            ),
            "dashboard:teacher_permission_action": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_permission_action",
                    kwargs={"request_id": self.download_request.id},
                ),
                lambda: {"action": "approve", "expiry_days": "7"},
            ),
            "dashboard:teacher_permissions_bulk_action": (
                self.teacher,
                lambda: reverse("dashboard:teacher_permissions_bulk_action"),
                lambda: {
                    "bulk_action": "approve",
                    "selected_ids": [str(self.download_request.id)],
                    "bulk_expiry_days": "7",
                },
            ),
            "dashboard:teacher_approve_for_all": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_approve_for_all",
                    kwargs={"item_id": self.material_item.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_course_create": (
                self.teacher,
                lambda: reverse("dashboard:teacher_course_create"),
                lambda: {
                    "title": "Created By Payload Factory",
                    "slug": "created-by-payload-factory",
                    "short_description": "Short desc",
                    "description": "Full desc",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_course_edit": (
                self.teacher,
                lambda: reverse("dashboard:teacher_course_edit", kwargs={"slug": self.course.slug}),
                lambda: {
                    "title": self.course.title,
                    "slug": self.course.slug,
                    "short_description": "Updated short",
                    "description": "Updated full",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_course_archive": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_archive", kwargs={"slug": self.course.slug}
                ),
                lambda: {},
            ),
            "dashboard:teacher_lesson_create": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_lesson_create", kwargs={"slug": self.course.slug}
                ),
                lambda: {
                    "title": "Payload Lesson 1",
                    "video_provider": "youtube",
                    "video_input": "dQw4w9WgXcQ",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_course_lesson_create": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_lesson_create", kwargs={"slug": self.course.slug}
                ),
                lambda: {
                    "title": "Payload Lesson 2",
                    "video_provider": "youtube",
                    "video_input": "dQw4w9WgXcQ",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_lesson_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_lesson_edit",
                    kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {
                    "title": self.lesson.title,
                    "video_provider": "youtube",
                    "video_input": "dQw4w9WgXcQ",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_course_lesson_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_lesson_edit",
                    kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {
                    "title": self.lesson.title,
                    "video_provider": "youtube",
                    "video_input": "dQw4w9WgXcQ",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_lesson_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_lesson_toggle_publish",
                    kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_course_lesson_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_lesson_toggle_publish",
                    kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_lesson_reorder": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_lesson_reorder",
                    kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {"direction": "down"},
            ),
            "dashboard:teacher_course_lesson_reorder": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_lesson_reorder",
                    kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
                ),
                lambda: {"direction": "down"},
            ),
            "dashboard:teacher_lesson_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_lesson_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "lesson_id": _build_disposable_lesson().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_course_lesson_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_lesson_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "lesson_id": _build_disposable_lesson().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_assignment_create": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_create", kwargs={"slug": self.course.slug}
                ),
                lambda: {
                    "title": "Payload Assignment 1",
                    "instructions": "Instructions",
                    "opens_at": "2026-01-01T00:00",
                    "due_at": "2027-01-01T00:00",
                    "max_score": "100",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_course_assignment_create": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_assignment_create",
                    kwargs={"slug": self.course.slug},
                ),
                lambda: {
                    "title": "Payload Assignment 2",
                    "instructions": "Instructions",
                    "opens_at": "2026-01-01T00:00",
                    "due_at": "2027-01-01T00:00",
                    "max_score": "100",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_assignment_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_edit",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                ),
                lambda: {
                    "title": self.assignment.title,
                    "instructions": "Updated instructions",
                    "opens_at": "2026-01-01T00:00",
                    "due_at": "2027-01-01T00:00",
                    "max_score": "100",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_course_assignment_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_assignment_edit",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                ),
                lambda: {
                    "title": self.assignment.title,
                    "instructions": "Updated instructions",
                    "opens_at": "2026-01-01T00:00",
                    "due_at": "2027-01-01T00:00",
                    "max_score": "100",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_assignment_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_toggle_publish",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_course_assignment_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_assignment_toggle_publish",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_assignment_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "assignment_id": _build_disposable_assignment().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_course_assignment_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_course_assignment_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "assignment_id": _build_disposable_assignment().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_assignment_attachment_add": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_attachment_add",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                ),
                lambda: {
                    "title": "Added Attachment",
                    "file": _make_pdf("added.pdf"),
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_assignment_attachment_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_attachment_edit",
                    kwargs={
                        "slug": self.course.slug,
                        "assignment_id": self.assignment.id,
                        "attachment_id": self.attachment.id,
                    },
                ),
                lambda: {"title": "Edited Attachment Title", "is_published": "on"},
            ),
            "dashboard:teacher_assignment_attachment_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_attachment_toggle_publish",
                    kwargs={
                        "slug": self.course.slug,
                        "assignment_id": self.assignment.id,
                        "attachment_id": self.attachment.id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_assignment_attachment_reorder": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_attachment_reorder",
                    kwargs={
                        "slug": self.course.slug,
                        "assignment_id": self.assignment.id,
                        "attachment_id": self.attachment.id,
                    },
                ),
                lambda: {"direction": "down"},
            ),
            "dashboard:teacher_assignment_attachment_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_assignment_attachment_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "assignment_id": self.assignment.id,
                        "attachment_id": _build_disposable_attachment().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_enrollment_action": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_enrollment_action",
                    kwargs={"enrollment_id": self.pending_enrollment.id},
                ),
                lambda: {"action": "approve"},
            ),
            "dashboard:teacher_enrollments_bulk_action": (
                self.teacher,
                lambda: reverse("dashboard:teacher_enrollments_bulk_action"),
                lambda: {
                    "action": "approve",
                    "enrollment_ids": [str(self.pending_enrollment.id)],
                },
            ),
            "dashboard:teacher_enrollment_manual": (
                self.teacher,
                lambda: reverse("dashboard:teacher_enrollment_manual"),
                lambda: {
                    "email": self.student_unenrolled.email,
                    "course_id": str(self.course.id),
                },
            ),
            "dashboard:teacher_submission_grade": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_submission_grade",
                    kwargs={"submission_id": self.submission.id},
                ),
                lambda: {"grade": "92.50", "feedback": "Well done!"},
            ),
            "dashboard:teacher_submission_unlock": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_submission_unlock",
                    kwargs={"submission_id": self.submission.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_student_toggle_active": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_student_toggle_active",
                    kwargs={"student_id": self.student_active.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_material_create": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_create", kwargs={"slug": self.course.slug}
                ),
                lambda: {
                    "title": "Payload Material Section",
                    "description": "Notes",
                    "order": "4",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_material_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_edit",
                    kwargs={"slug": self.course.slug, "material_id": self.material.id},
                ),
                lambda: {
                    "title": self.material.title,
                    "description": "Updated notes",
                    "order": "1",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_material_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_toggle_publish",
                    kwargs={"slug": self.course.slug, "material_id": self.material.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_material_archive": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_archive",
                    kwargs={"slug": self.course.slug, "material_id": self.material.id},
                ),
                lambda: {},
            ),
            "dashboard:teacher_material_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "material_id": _build_disposable_material().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_material_item_create": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_item_create",
                    kwargs={"slug": self.course.slug, "material_id": self.material.id},
                ),
                lambda: {
                    "title": "Payload External Link",
                    "item_type": MaterialItem.ItemType.LINK,
                    "external_url": "https://example.com/resource",
                    "order": "3",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_material_item_edit": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_item_edit",
                    kwargs={
                        "slug": self.course.slug,
                        "material_id": self.material.id,
                        "item_id": self.material_item.id,
                    },
                ),
                lambda: {
                    "title": self.material_item.title,
                    "item_type": MaterialItem.ItemType.FILE,
                    "download_policy": MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
                    "order": "1",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_material_item_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_item_toggle_publish",
                    kwargs={
                        "slug": self.course.slug,
                        "material_id": self.material.id,
                        "item_id": self.material_item.id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_material_item_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_item_delete",
                    kwargs={
                        "slug": self.course.slug,
                        "material_id": self.material.id,
                        "item_id": _build_disposable_material_item().id,
                    },
                ),
                lambda: {},
            ),
            "dashboard:teacher_material_item_reorder": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_item_reorder",
                    kwargs={
                        "slug": self.course.slug,
                        "material_id": self.material.id,
                        "item_id": self.material_item.id,
                    },
                ),
                lambda: {"direction": "down"},
            ),
            "dashboard:teacher_material_item_policy": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_material_item_policy",
                    kwargs={
                        "slug": self.course.slug,
                        "material_id": self.material.id,
                        "item_id": self.material_item.id,
                    },
                ),
                lambda: {
                    "target_policy": MaterialItem.DownloadPolicy.OPEN_TO_ENROLLED,
                },
            ),
            "dashboard:teacher_settings": (
                self.teacher,
                lambda: reverse("dashboard:teacher_settings"),
                lambda: {
                    "site_name": "Mathematics Academy",
                    "teacher_name": "Prof. Euler",
                    "contact_email": "euler@example.com",
                },
            ),
            "dashboard:teacher_faq_create": (
                self.teacher,
                lambda: reverse("dashboard:teacher_faq_create"),
                lambda: {
                    "question": "Created FAQ Question?",
                    "answer": "Created FAQ Answer.",
                    "order": "5",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_faq_edit": (
                self.teacher,
                lambda: reverse("dashboard:teacher_faq_edit", kwargs={"faq_id": self.faq.id}),
                lambda: {
                    "question": self.faq.question,
                    "answer": "Updated FAQ Answer.",
                    "order": "1",
                    "is_published": "on",
                },
            ),
            "dashboard:teacher_faq_toggle_publish": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_faq_toggle_publish", kwargs={"faq_id": self.faq.id}
                ),
                lambda: {},
            ),
            "dashboard:teacher_faq_reorder": (
                self.teacher,
                lambda: reverse("dashboard:teacher_faq_reorder", kwargs={"faq_id": self.faq.id}),
                lambda: {"direction": "down"},
            ),
            "dashboard:teacher_faq_delete": (
                self.teacher,
                lambda: reverse(
                    "dashboard:teacher_faq_delete",
                    kwargs={"faq_id": _build_disposable_faq().id},
                ),
                lambda: {},
            ),
            "admin_login": (
                None,
                lambda: reverse("admin_login"),
                lambda: {"username": self.superuser.email, "password": self.password},
            ),
            "admin:logout": (
                self.superuser,
                lambda: reverse("admin:logout"),
                lambda: {},
            ),
            "admin:password_change": (
                self.superuser,
                lambda: reverse("admin:password_change"),
                lambda: {
                    "old_password": self.password,
                    "new_password1": self.password,
                    "new_password2": self.password,
                },
            ),
            "admin:auth_user_password_change": (
                self.superuser,
                lambda: reverse(
                    "admin:auth_user_password_change", args=[self.student_unenrolled.pk]
                ),
                lambda: {
                    "password1": self.password,
                    "password2": self.password,
                },
            ),
        }

        # Rule 5: No silent skips — every mutating route must have a payload factory or explicit exemption
        uncovered = (
            set(mutating_keys)
            - set(payload_factories.keys())
            - set(MUTATING_PAYLOAD_FACTORY_EXEMPTIONS.keys())
        )
        assert not uncovered, (
            f"Mutating routes missing payload factories and not in MUTATING_PAYLOAD_FACTORY_EXEMPTIONS: "
            f"{sorted(uncovered)}"
        )
        for exempt_key, reason in MUTATING_PAYLOAD_FACTORY_EXEMPTIONS.items():
            assert reason.strip(), f"Exemption for {exempt_key} must have a non-empty reason."

        csrf_client = Client(enforce_csrf_checks=True)
        guest_client = Client()
        unenrolled_client = Client()
        unenrolled_client.force_login(self.student_unenrolled)
        superuser_client = Client()
        superuser_client.force_login(self.superuser)

        for route_key in mutating_keys:
            spec = ACCESS_MATRIX[route_key]
            url = self._resolve_route_url(route_key, actor_user=self.teacher)

            # 1. POST-only routes must return 405 on GET
            if "GET" not in spec.methods:
                get_client = superuser_client if route_key == "admin:logout" else guest_client
                get_resp = get_client.get(url)
                assert get_resp.status_code == 405, (
                    f"POST-only route {route_key} returned {get_resp.status_code} on GET (expected 405)."
                )

            # 2. POST without CSRF token must return 403 (or 401 on google_login_by_token which uses g_csrf_token)
            csrf_resp = csrf_client.post(url, {})
            expected_csrf_failure = (401, 403) if route_key == "google_login_by_token" else (403,)
            assert csrf_resp.status_code in expected_csrf_failure, (
                f"Mutating route {route_key} did not return {expected_csrf_failure} on POST without CSRF token (got {csrf_resp.status_code})."
            )

            # 3. POST by wrong role must be refused
            if spec.classification == "teacher":
                wrong_resp = unenrolled_client.post(url, {})
                assert wrong_resp.status_code in (302, 403), (
                    f"Teacher route {route_key} did not refuse student POST (got {wrong_resp.status_code})."
                )
            elif spec.classification == "enrolled":
                wrong_resp = unenrolled_client.post(url, {})
                assert wrong_resp.status_code in (302, 403), (
                    f"Enrolled route {route_key} did not refuse unenrolled student POST (got {wrong_resp.status_code})."
                )
            elif spec.classification == "authenticated":
                wrong_resp = guest_client.post(url, {})
                assert wrong_resp.status_code in (302, 403), (
                    f"Authenticated route {route_key} did not refuse guest POST (got {wrong_resp.status_code})."
                )

            # 4. POST by authorized role with payload factory must succeed (200 or 302)
            if route_key in payload_factories:
                auth_user, url_fn, payload_fn = payload_factories[route_key]
                auth_client = Client()
                if auth_user is not None:
                    auth_user.refresh_from_db()
                    auth_client.force_login(auth_user)
                target_url = url_fn()
                with _allow_third_party_template_vars(route_key):
                    right_resp = auth_client.post(target_url, payload_fn(), REMOTE_ADDR="127.0.0.1")
                assert right_resp.status_code in (200, 302), (
                    f"Authorized POST with payload factory on {route_key} returned {right_resp.status_code}"
                )
                # Restore state if toggled or mutated
                if route_key in ("courses:enroll", "dashboard:teacher_enrollment_manual"):
                    Enrollment.objects.filter(student=self.student_unenrolled).delete()
                elif route_key == "dashboard:teacher_student_toggle_active":
                    self.student_active.is_active = True
                    self.student_active.save(update_fields=["is_active"])
                elif route_key == "dashboard:teacher_course_archive":
                    self.course.is_published = True
                    self.course.is_archived = False
                    self.course.save(update_fields=["is_published", "is_archived"])
                elif "toggle_publish" in route_key or "archive" in route_key:
                    Lesson.objects.filter(pk=self.lesson.pk).update(is_published=True)
                    Assignment.objects.filter(pk=self.assignment.pk).update(is_published=True)
                    AssignmentAttachment.objects.filter(pk=self.attachment.pk).update(
                        is_published=True
                    )
                    CourseMaterial.objects.filter(pk=self.material.pk).update(
                        is_published=True, is_archived=False
                    )
                    MaterialItem.objects.filter(pk=self.material_item.pk).update(is_published=True)
                    FAQItem.objects.filter(pk=self.faq.pk).update(is_published=True)

    def test_mismatched_parent_ids_return_404_on_all_multi_id_routes(self):
        """
        Approval Rule #6: For every route with two or more IDs/slugs, requesting an object
        from `other_course` (or another parent) under `self.course.slug` must return 404.
        """
        mismatched_cases = {
            # Learn routes (course_slug + lesson_id / item_id)
            "learn:lesson": (
                "GET",
                self.student_active,
                {"course_slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "learn:toggle_complete": (
                "POST",
                self.student_active,
                {"course_slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "learn:playback_position": (
                "POST",
                self.student_active,
                {"course_slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "learn:material_request": (
                "POST",
                self.student_active,
                {"course_slug": self.course.slug, "item_id": self.other_material_item.id},
            ),
            "learn:material_cancel": (
                "POST",
                self.student_active,
                {"course_slug": self.course.slug, "item_id": self.other_material_item.id},
            ),
            "learn:material_download": (
                "GET",
                self.student_active,
                {"course_slug": self.course.slug, "item_id": self.other_material_item.id},
            ),
            "learn:material_preview": (
                "GET",
                self.student_active,
                {"course_slug": self.course.slug, "item_id": self.other_material_item.id},
            ),
            # Assignments routes (slug + assignment_id / submission_id / attachment_id)
            "assignments:detail": (
                "GET",
                self.student_active,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "assignments:download": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "submission_id": self.other_submission.id},
            ),
            "assignments:attachment_download": (
                "GET",
                self.student_active,
                {"slug": self.course.slug, "attachment_id": self.other_attachment.id},
            ),
            "assignments:attachment_preview": (
                "GET",
                self.student_active,
                {"slug": self.course.slug, "attachment_id": self.other_attachment.id},
            ),
            # Dashboard lesson routes (slug + lesson_id)
            "dashboard:teacher_lesson_edit": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_course_lesson_edit": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_lesson_toggle_publish": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_course_lesson_toggle_publish": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_lesson_reorder": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_course_lesson_reorder": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_lesson_delete": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            "dashboard:teacher_course_lesson_delete": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "lesson_id": self.other_lesson.id},
            ),
            # Dashboard assignment routes (slug + assignment_id)
            "dashboard:teacher_assignment_edit": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_course_assignment_edit": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_assignment_toggle_publish": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_course_assignment_toggle_publish": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_assignment_delete": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_course_assignment_delete": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_assignment_attachment_add": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_course_assignment_submissions": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            "dashboard:teacher_missed_deadlines": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "assignment_id": self.other_assignment.id},
            ),
            # Dashboard assignment attachment routes (slug + assignment_id + attachment_id)
            "dashboard:teacher_assignment_attachment_edit": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "assignment_id": self.assignment.id,
                    "attachment_id": self.other_attachment.id,
                },
            ),
            "dashboard:teacher_assignment_attachment_toggle_publish": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "assignment_id": self.assignment.id,
                    "attachment_id": self.other_attachment.id,
                },
            ),
            "dashboard:teacher_assignment_attachment_reorder": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "assignment_id": self.assignment.id,
                    "attachment_id": self.other_attachment.id,
                },
            ),
            "dashboard:teacher_assignment_attachment_delete": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "assignment_id": self.assignment.id,
                    "attachment_id": self.other_attachment.id,
                },
            ),
            "dashboard:teacher_assignment_attachment_downloads": (
                "GET",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "assignment_id": self.assignment.id,
                    "attachment_id": self.other_attachment.id,
                },
            ),
            # Dashboard material routes (slug + material_id)
            "dashboard:teacher_material_edit": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "material_id": self.other_material.id},
            ),
            "dashboard:teacher_material_toggle_publish": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "material_id": self.other_material.id},
            ),
            "dashboard:teacher_material_archive": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "material_id": self.other_material.id},
            ),
            "dashboard:teacher_material_delete": (
                "POST",
                self.teacher,
                {"slug": self.course.slug, "material_id": self.other_material.id},
            ),
            "dashboard:teacher_material_item_create": (
                "GET",
                self.teacher,
                {"slug": self.course.slug, "material_id": self.other_material.id},
            ),
            # Dashboard material item routes (slug + material_id + item_id)
            "dashboard:teacher_material_item_edit": (
                "GET",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.other_material_item.id,
                },
            ),
            "dashboard:teacher_material_item_toggle_publish": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.other_material_item.id,
                },
            ),
            "dashboard:teacher_material_item_delete": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.other_material_item.id,
                },
            ),
            "dashboard:teacher_material_item_reorder": (
                "POST",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.other_material_item.id,
                },
            ),
            "dashboard:teacher_material_item_policy": (
                "GET",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.other_material_item.id,
                },
            ),
            "dashboard:teacher_material_item_history": (
                "GET",
                self.teacher,
                {
                    "slug": self.course.slug,
                    "material_id": self.material.id,
                    "item_id": self.other_material_item.id,
                },
            ),
        }

        # Ensure no multi-parameter application route was missed
        discovered = walk_urlconf("config.urls")
        for entry in discovered:
            rk = entry["route_key"]
            if rk.startswith(("admin", "<unnamed:", "account_reset_password_from_key")):
                continue
            param_count = entry["pattern"].count("<")
            if param_count >= 2:
                assert rk in mismatched_cases, (
                    f"Multi-parameter route {rk} ({entry['pattern']}) must be included in "
                    "mismatched_cases for cross-course 404 verification."
                )

        for route_key, (method, user, kwargs) in mismatched_cases.items():
            c = Client()
            c.force_login(user)
            url = reverse(route_key, kwargs=kwargs)
            resp = c.get(url) if method == "GET" else c.post(url, {})
            assert resp.status_code == 404, (
                f"Mismatched-parent check failed on {route_key} with kwargs={kwargs}: "
                f"expected 404, got {resp.status_code}"
            )

    def test_removed_allauth_routes_return_404_and_are_unregistered(self):
        """
        Item 5: Verify that every unused/unlinked allauth route (`google_login_by_token`,
        `account_confirm_login_code`, `account_email`, `account_reauthenticate`,
        `account_set_password`, `account_inactive`, `socialaccount_login_cancelled`,
        `socialaccount_login_error`, `socialaccount_signup`, `socialaccount_connections`,
        and legacy social redirects) is removed from `config.urls` (raises `NoReverseMatch`)
        and returns 404 on both GET and POST.
        """
        accounts_prefix = reverse("account_login").removesuffix("login/")
        guest_client = Client()
        auth_client = Client()
        auth_client.force_login(self.student_active)

        for route_name, expected_path in REMOVED_ALLAUTH_ROUTES.items():
            if not route_name.startswith("<unnamed:"):
                with pytest.raises(NoReverseMatch):
                    reverse(route_name, urlconf="config.urls")

            # Construct path relative to reverse("account_login") prefix
            rel_suffix = expected_path.removeprefix("/accounts/")
            target_url = f"{accounts_prefix}{rel_suffix}"
            assert guest_client.get(target_url).status_code == 404, (
                f"Removed route {route_name} ({target_url}) did not return 404 on guest GET."
            )
            assert guest_client.post(target_url, {}).status_code == 404, (
                f"Removed route {route_name} ({target_url}) did not return 404 on guest POST."
            )
            assert auth_client.get(target_url).status_code == 404, (
                f"Removed route {route_name} ({target_url}) did not return 404 on authenticated GET."
            )
            assert auth_client.post(target_url, {}).status_code == 404, (
                f"Removed route {route_name} ({target_url}) did not return 404 on authenticated POST."
            )

    def test_enrolled_routes_enforce_object_state_variants(self):
        """
        Item 3: Verify object-state variants for enrolled-class routes across all 8 actors:
        - `draft_lesson` (`lesson.is_published = False`)
        - `assignment_unpublished_lesson` (`assignment.lesson = draft_lesson`)
        - `unpublished_assignment` (`assignment.is_published = False`)
        - `assignment_before_opens_at` (`assignment.opens_at > now`)
        - `unpublished_attachment` (`attachment.is_published = False`)
        - `archived_course` (`course.is_archived = True`: active student & staff keep access, others get 404)
        - `unpublished_course` (`course.is_published = False`: only staff keep access, others get 404)
        """
        actor_users = {
            "guest": None,
            "student_unenrolled": self.student_unenrolled,
            "student_pending": self.student_pending,
            "student_revoked": self.student_revoked,
            "student_active": self.student_active,
            "student_other_course": self.student_other_course,
            "teacher": self.teacher,
            "superuser": self.superuser,
        }
        clients = {}
        for actor_name, user in actor_users.items():
            c = Client()
            if user is not None:
                c.force_login(user)
            clients[actor_name] = c

        @contextmanager
        def _apply_object_state(variant_name: str):
            orig_lesson_pub = self.lesson.is_published
            orig_assign_pub = self.assignment.is_published
            orig_assign_opens = self.assignment.opens_at
            orig_att_pub = self.attachment.is_published
            orig_course_arch = self.course.is_archived
            orig_course_pub = self.course.is_published
            try:
                if variant_name in ("draft_lesson", "assignment_unpublished_lesson"):
                    Lesson.objects.filter(pk=self.lesson.pk).update(is_published=False)
                elif variant_name == "unpublished_assignment":
                    Assignment.objects.filter(pk=self.assignment.pk).update(is_published=False)
                elif variant_name == "assignment_before_opens_at":
                    Assignment.objects.filter(pk=self.assignment.pk).update(
                        opens_at=timezone.now() + timedelta(days=3)
                    )
                elif variant_name == "unpublished_attachment":
                    AssignmentAttachment.objects.filter(pk=self.attachment.pk).update(
                        is_published=False
                    )
                elif variant_name == "archived_course":
                    Course.objects.filter(pk=self.course.pk).update(is_archived=True)
                elif variant_name == "unpublished_course":
                    Course.objects.filter(pk=self.course.pk).update(is_published=False)
                yield
            finally:
                Lesson.objects.filter(pk=self.lesson.pk).update(is_published=orig_lesson_pub)
                Assignment.objects.filter(pk=self.assignment.pk).update(
                    is_published=orig_assign_pub,
                    opens_at=orig_assign_opens,
                )
                AssignmentAttachment.objects.filter(pk=self.attachment.pk).update(
                    is_published=orig_att_pub
                )
                Course.objects.filter(pk=self.course.pk).update(
                    is_archived=orig_course_arch,
                    is_published=orig_course_pub,
                )

        failures = []
        for variant_name, routes_map in ENROLLED_OBJECT_STATE_EXPECTATIONS.items():
            with _apply_object_state(variant_name):
                for route_key, methods_map in routes_map.items():
                    for method, actor_map in methods_map.items():
                        for actor_name, expected_code in actor_map.items():
                            actor_user = actor_users[actor_name]
                            url = self._resolve_route_url(route_key, actor_user=actor_user)
                            c = clients[actor_name]
                            if method == "GET":
                                resp = c.get(url, REMOTE_ADDR="127.0.0.1")
                            else:
                                if route_key == "learn:playback_position":
                                    post_data = {"position": "30"}
                                elif route_key == "assignments:detail":
                                    post_data = {"content_text": "Variant submission text."}
                                else:
                                    post_data = {}
                                resp = c.post(url, post_data, REMOTE_ADDR="127.0.0.1")

                            if resp.status_code != expected_code:
                                failures.append(
                                    f"variant={variant_name} {route_key} [{method}] actor={actor_name}: "
                                    f"got {resp.status_code}, expected {expected_code}"
                                )

        assert not failures, "Object-state variant assertions failed:\n" + "\n".join(failures)


@pytest.mark.django_db
class TestPhase8B1BugRegressions(_MatrixWorldMixin):
    """
    Item 4: Dedicated regression tests for each bug uncovered and fixed in Chunk 8B-1.
    """

    def test_teacher_role_without_is_staff_flag_is_recognized_by_is_teacher_user(self):
        """
        Bug #1 (`is_staff` direct checks vs `is_teacher_user`):
        Verify that `courses/views.py`, `courses/permissions.py`, `courses/views_materials.py`,
        and `assignments/views.py` use `is_teacher_user(request.user)` instead of direct
        `request.user.is_staff` checks, so a teacher with `role=TEACHER` and `is_staff=False`
        (`self.teacher_non_staff`) can preview draft lessons, unpublished courses, and
        unpublished assignments consistently with `@teacher_required`.
        """
        c = Client()
        c.force_login(self.teacher_non_staff)

        # Draft lesson must return 200 to teacher_non_staff (failed with 404 before Bug #1 fix)
        Lesson.objects.filter(pk=self.lesson.pk).update(is_published=False)
        try:
            resp_lesson = c.get(
                reverse(
                    "learn:lesson",
                    kwargs={"course_slug": self.course.slug, "lesson_id": self.lesson.id},
                )
            )
            assert resp_lesson.status_code == 200
        finally:
            Lesson.objects.filter(pk=self.lesson.pk).update(is_published=True)

        # Unpublished assignment must return 200 to teacher_non_staff (failed with 404 before Bug #1 fix)
        Assignment.objects.filter(pk=self.assignment.pk).update(is_published=False)
        try:
            resp_assign = c.get(
                reverse(
                    "assignments:detail",
                    kwargs={"slug": self.course.slug, "assignment_id": self.assignment.id},
                )
            )
            assert resp_assign.status_code == 200
        finally:
            Assignment.objects.filter(pk=self.assignment.pk).update(is_published=True)

        # Unpublished course materials must return 200 to teacher_non_staff (failed with 404 before Bug #1 fix)
        Course.objects.filter(pk=self.course.pk).update(is_published=False)
        try:
            resp_mat = c.get(reverse("learn:materials", kwargs={"course_slug": self.course.slug}))
            assert resp_mat.status_code == 200
        finally:
            Course.objects.filter(pk=self.course.pk).update(is_published=True)

    def test_material_cancel_request_denies_non_active_enrolled_students(self):
        """
        Bug #2 (`learn:material_cancel` missing `check_material_access`):
        Unenrolled, pending, revoked, and other-course students must receive 403 Forbidden
        (not 302 redirect) on `learn:material_cancel`.
        """
        url = reverse(
            "learn:material_cancel",
            kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
        )
        for student in (
            self.student_unenrolled,
            self.student_pending,
            self.student_revoked,
            self.student_other_course,
        ):
            c = Client()
            c.force_login(student)
            resp = c.post(url, {})
            assert resp.status_code == 403

    def test_post_only_views_return_405_on_guest_get_before_auth_redirect(self):
        """
        Bug #3 (Decorator ordering on POST-only routes):
        `@require_POST` / `@require_http_methods(["POST"])` must wrap `@login_required` /
        `@teacher_required` so GET requests by unauthenticated guests receive 405, not 302.
        """
        guest = Client()
        for url in (
            reverse(
                "learn:material_request",
                kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
            ),
            reverse(
                "learn:material_cancel",
                kwargs={"course_slug": self.course.slug, "item_id": self.material_item.id},
            ),
            reverse(
                "notifications:mark_read",
                kwargs={"notification_id": self.notifications_by_user[self.student_active.id].id},
            ),
            reverse("notifications:mark_all_read"),
            reverse("dashboard:teacher_course_archive", kwargs={"slug": self.course.slug}),
            reverse(
                "dashboard:teacher_lesson_delete",
                kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
            ),
            reverse("dashboard:teacher_enrollments_bulk_action"),
        ):
            assert guest.get(url).status_code == 405

    def test_material_download_and_preview_check_course_access_before_item_lookup(self):
        """
        Bug #4 (`MaterialItem` lookup before `check_material_access`):
        An unenrolled student probing a nonexistent `item_id` on `learn:material_download`
        or `learn:material_preview` must receive 403 Forbidden (course access denied),
        never 404 Not Found (which would leak item_id existence).
        """
        c = Client()
        c.force_login(self.student_unenrolled)
        nonexistent_item_id = 9999999
        dl_url = reverse(
            "learn:material_download",
            kwargs={"course_slug": self.course.slug, "item_id": nonexistent_item_id},
        )
        prev_url = reverse(
            "learn:material_preview",
            kwargs={"course_slug": self.course.slug, "item_id": nonexistent_item_id},
        )
        assert c.get(dl_url).status_code == 403
        assert c.get(prev_url).status_code == 403

    def test_assignments_download_redirects_guest_to_login_302(self):
        """
        Bug #5 (`assignments:download` guest status):
        Unauthenticated guests requesting `assignments:download` must be redirected
        to the login page (302), matching `learn:material_download` and `assignments:attachment_download`.
        """
        guest = Client()
        url = reverse(
            "assignments:download",
            kwargs={"slug": self.course.slug, "submission_id": self.submission.id},
        )
        resp = guest.get(url)
        assert resp.status_code == 302
        assert reverse("account_login") in resp["Location"]

    def test_teacher_lesson_delete_blocks_lesson_with_progress_and_linked_assignment(self):
        """
        Bug #6 & #7 (`lesson.progress.exists()`, `", ".join(str(r) for r in reasons)`,
        and `student_progress_count` in `teacher_lesson_edit_view`):
        Deleting a lesson that has both student progress (`self.lesson_progress`) and a
        linked assignment (`self.assignment`) must not raise `AttributeError` or `TypeError`
        and must preserve the lesson while redirecting with an error message.
        Also verifies invalid POST to `teacher_lesson_edit_view` includes `student_progress_count`.
        """
        c = Client()
        c.force_login(self.teacher)
        delete_url = reverse(
            "dashboard:teacher_lesson_delete",
            kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
        )
        resp = c.post(delete_url, {})
        assert resp.status_code == 302
        assert Lesson.objects.filter(pk=self.lesson.pk).exists()

        edit_url = reverse(
            "dashboard:teacher_lesson_edit",
            kwargs={"slug": self.course.slug, "lesson_id": self.lesson.id},
        )
        invalid_edit_resp = c.post(edit_url, {"title": ""})
        assert invalid_edit_resp.status_code == 200
        assert invalid_edit_resp.context["student_progress_count"] >= 1

    def test_teacher_enrollments_bulk_action_with_empty_ids_does_not_shadow_gettext(self):
        """
        Bug #8 (`UnboundLocalError: cannot access local variable '_'` in `teacher_enrollments_bulk_action_view`):
        Posting to `dashboard:teacher_enrollments_bulk_action` with empty `enrollment_ids`
        must redirect cleanly (302) with a warning message without raising `UnboundLocalError`.
        """
        c = Client()
        c.force_login(self.teacher)
        url = reverse("dashboard:teacher_enrollments_bulk_action")
        resp = c.post(url, {"action": "approve", "enrollment_ids": []})
        assert resp.status_code == 302

    def test_material_request_duplicate_atomic_savepoint_recovery(self):
        """
        Bug #9 (`DownloadRequest.objects.create` inside `with transaction.atomic():`):
        When an `IntegrityError` occurs on `DownloadRequest.objects.create` in
        `material_request_download_view`, the atomic savepoint must allow subsequent
        queries in the same view/transaction to succeed.
        """
        from unittest.mock import patch

        from django.db import IntegrityError

        req_item = MaterialItem.objects.create(
            material=self.material,
            title="Restricted Material",
            item_type=MaterialItem.ItemType.FILE,
            file=_make_pdf("restricted.pdf"),
            download_policy=MaterialItem.DownloadPolicy.REQUEST_REQUIRED,
            order=5,
            is_published=True,
        )
        c = Client()
        c.force_login(self.student_active)
        url = reverse(
            "learn:material_request",
            kwargs={"course_slug": self.course.slug, "item_id": req_item.id},
        )
        with patch.object(
            DownloadRequest.objects,
            "create",
            side_effect=IntegrityError("Simulated concurrent duplicate request"),
        ):
            resp = c.post(url, {"request_note": "Concurrent request"})
        assert resp.status_code == 302

    def test_lesson_and_material_item_forms_render_cleanly_under_invalid_var_sentinel(self):
        """
        Bug #10 (`lesson_form.html` `form.description` and `item_form.html` `if item and item.file`):
        Rendering `dashboard:teacher_lesson_create` and `dashboard:teacher_material_item_create`
        must succeed with zero undefined template variable errors under `InvalidVarSentinel`.
        """
        c = Client()
        c.force_login(self.teacher)
        resp_lesson = c.get(
            reverse("dashboard:teacher_lesson_create", kwargs={"slug": self.course.slug})
        )
        assert resp_lesson.status_code == 200
        resp_item = c.get(
            reverse(
                "dashboard:teacher_material_item_create",
                kwargs={"slug": self.course.slug, "material_id": self.material.id},
            )
        )
        assert resp_item.status_code == 200
