import logging

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.courses.models import Enrollment, EnrollmentEvent
from apps.notifications.models import Notification
from apps.notifications.services import create_notification
from django.urls import reverse

logger = logging.getLogger(__name__)

# Strictly allowed state transitions (Requirement 4)
# pending -> active, pending -> revoked, active -> revoked, revoked -> active
ALLOWED_ENROLLMENT_TRANSITIONS: dict[str, set[str]] = {
    Enrollment.Status.PENDING: {Enrollment.Status.ACTIVE, Enrollment.Status.REVOKED},
    Enrollment.Status.ACTIVE: {Enrollment.Status.REVOKED},
    Enrollment.Status.REVOKED: {Enrollment.Status.ACTIVE},
}


def transition_enrollment_status(
    enrollment_id: int,
    new_status: str,
    actor,
    note: str = "",
) -> tuple[Enrollment, bool, str]:
    """
    Central, race-safe state transition service for Enrollment objects.
    Enforces strict allowed transitions, records an EnrollmentEvent,
    and safely notifies the student.

    Guarantees:
    - Atomicity & row locking via select_for_update()
    - Strict validation of allowed transitions (pending->active, pending->revoked, active->revoked, revoked->active)
    - Revoke and restore never touch progress or submissions
    - Audit log written to EnrollmentEvent
    - Exactly one notification sent per transition via transaction.on_commit
    - Notification failure never blocks or fails the transaction
    """
    with transaction.atomic():
        try:
            enrollment = (
                Enrollment.objects.select_for_update()
                .select_related("student", "course")
                .get(pk=enrollment_id)
            )
        except Enrollment.DoesNotExist:
            return None, False, _("Enrollment record does not exist.")

        old_status = enrollment.status

        # Idempotent check
        if old_status == new_status:
            return enrollment, False, _("Enrollment is already %(status)s.") % {"status": new_status}

        # Transition validation
        allowed_targets = ALLOWED_ENROLLMENT_TRANSITIONS.get(old_status, set())
        if new_status not in allowed_targets:
            msg = _("Invalid enrollment status transition from '%(old)s' to '%(new)s'.") % {
                "old": old_status,
                "new": new_status,
            }
            logger.warning("Invalid enrollment transition rejected for enrollment %s: %s -> %s", enrollment.id, old_status, new_status)
            raise ValueError(msg)

        # Apply transition
        enrollment.status = new_status
        enrollment.save(update_fields=["status", "updated_at"])

        # Write audit event
        EnrollmentEvent.objects.create(
            enrollment=enrollment,
            actor=actor,
            from_status=old_status,
            to_status=new_status,
            note=note,
        )

        logger.info(
            "Teacher/Actor %s transitioned enrollment %s (student: %s, course: %s) from %s to %s",
            getattr(actor, "id", None),
            enrollment.id,
            enrollment.student_id,
            enrollment.course.slug,
            old_status,
            new_status,
        )

        # Send student notification safely via transaction.on_commit (one per student)
        student = enrollment.student
        course = enrollment.course

        def send_enrollment_notification():
            try:
                if new_status == Enrollment.Status.ACTIVE:
                    create_notification(
                        recipient=student,
                        kind=Notification.Kind.ENROLLMENT_APPROVED,
                        title=str(_("Enrollment Approved: %(title)s") % {"title": course.title}),
                        body=str(_(
                            "Your enrollment for %(title)s has been approved! You now have full access to all lessons and assignments."
                        ) % {"title": course.title}),
                        url=reverse("learn:course", kwargs={"course_slug": course.slug}),
                    )
                elif new_status == Enrollment.Status.REVOKED:
                    create_notification(
                        recipient=student,
                        kind=Notification.Kind.ENROLLMENT_REVOKED,
                        title=str(_("Enrollment Revoked: %(title)s") % {"title": course.title}),
                        body=str(_(
                            "Your access to %(title)s has been revoked by the instructor."
                        ) % {"title": course.title}),
                        url=reverse("courses:detail", kwargs={"slug": course.slug}),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to send enrollment notification for student %s in course %s: %s",
                    student.id,
                    course.slug,
                    exc,
                )

        if new_status in (Enrollment.Status.ACTIVE, Enrollment.Status.REVOKED):
            transaction.on_commit(send_enrollment_notification)

        status_display = enrollment.get_status_display()
        return enrollment, True, _("Enrollment updated to %(status)s.") % {"status": status_display}
