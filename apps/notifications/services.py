import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string

from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


def send_notification_email(notification_id: int) -> bool:
    """
    Sends an email notification if NOTIFY_BY_EMAIL is enabled in settings.
    Wrapped in try-except so SMTP or delivery errors never block application workflows.
    """
    notify_by_email = getattr(settings, "NOTIFY_BY_EMAIL", False)
    if not notify_by_email:
        return False

    try:
        notification = Notification.objects.select_related("recipient").get(pk=notification_id)
        recipient = notification.recipient
        if not recipient.email or not recipient.is_active:
            return False

        site_url = getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
        full_url = f"{site_url}{notification.url}" if notification.url else site_url

        context = {
            "recipient": recipient,
            "notification": notification,
            "action_url": full_url,
            "site_url": site_url,
        }

        subject = f"[{settings.DEFAULT_FROM_EMAIL.split('<')[0].strip() or 'Teaching Platform'}] {notification.title}"
        text_content = render_to_string("emails/notification_email.txt", context)
        html_content = render_to_string("emails/notification_email.html", context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient.email],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.error(
            "Failed to send notification email for notification_id=%s: %s",
            notification_id,
            exc,
            exc_info=True,
        )
        return False


def create_notification(
    recipient,
    kind: str,
    title: str,
    body: str,
    url: str = "",
) -> Notification:
    """
    Creates and persists a Notification record for a user.
    Schedules asynchronous email notification dispatch via transaction.on_commit.
    """
    notification = Notification.objects.create(
        recipient=recipient,
        kind=kind,
        title=title,
        body=body,
        url=url,
    )

    # Trigger email dispatch only after current database transaction successfully commits
    transaction.on_commit(lambda: send_notification_email(notification.id))

    return notification
