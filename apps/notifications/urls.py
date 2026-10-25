from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list_view, name="list"),
    path("<int:notification_id>/read/", views.mark_notification_read_view, name="mark_read"),
    path("mark-all-read/", views.mark_all_notifications_read_view, name="mark_all_read"),
]
