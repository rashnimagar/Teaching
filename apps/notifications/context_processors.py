import logging

from django.db import DatabaseError

logger = logging.getLogger(__name__)


def notifications_context(request):
    """
    Supplies the unread notifications count and formatted badge string to templates.
    Catches database errors gracefully to prevent page crashes during outages.
    Executes in a single bounded query for authenticated users; 0 queries for guests.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "unread_notifications_display": "",
        }

    try:
        count = user.notifications.filter(read_at__isnull=True).count()
    except (DatabaseError, Exception) as exc:
        logger.warning(
            "Failed to fetch unread notification count for user %s: %s",
            getattr(user, "pk", "unknown"),
            exc,
        )
        count = 0

    display = "99+" if count > 99 else (str(count) if count > 0 else "")

    return {
        "unread_notifications_count": count,
        "unread_notifications_display": display,
    }
