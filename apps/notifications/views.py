from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.notifications.models import Notification


@login_required
def notification_list_view(request):
    """
    Displays paginated list of notifications for the authenticated user (newest first).
    Strict student isolation: only the user's own notifications are queried.
    """
    qs = request.user.notifications.all().order_by("-created_at")
    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Attach is_safe_url boolean to each item for secure link rendering
    allowed_hosts = {request.get_host()}
    require_https = request.is_secure()
    for notif in page_obj:
        if notif.url:
            notif.has_safe_url = url_has_allowed_host_and_scheme(
                notif.url,
                allowed_hosts=allowed_hosts,
                require_https=require_https,
            ) and notif.url.startswith("/") and not notif.url.startswith("//")
        else:
            notif.has_safe_url = False

    return render(
        request,
        "notifications/notification_list.html",
        {
            "page_obj": page_obj,
            "notifications": page_obj.object_list,
        },
    )


@login_required
@require_POST
def mark_notification_read_view(request, notification_id: int):
    """
    Marks a single notification as read.
    Enforces student isolation: 404 if notification belongs to another user.
    """
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not notification.read_at:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])

    # If an internal action URL exists, redirect to it; otherwise redirect to list
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)

    if notification.url and url_has_allowed_host_and_scheme(
        notification.url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ) and notification.url.startswith("/") and not notification.url.startswith("//"):
        return redirect(notification.url)

    return redirect("notifications:list")


@login_required
@require_POST
def mark_all_notifications_read_view(request):
    """
    Marks all unread notifications of the authenticated user as read.
    """
    count = request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    if count > 0:
        messages.success(request, f"Marked {count} notification{'s' if count != 1 else ''} as read.")
    else:
        messages.info(request, "No unread notifications.")

    return redirect("notifications:list")
