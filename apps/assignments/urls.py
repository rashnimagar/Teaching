from django.urls import path

from apps.assignments import views

app_name = "assignments"

urlpatterns = [
    path("assignments/", views.course_assignments_view, name="list"),
    path("assignments/<int:assignment_id>/", views.assignment_detail_view, name="detail"),
    path(
        "submissions/<int:submission_id>/download/",
        views.submission_download_view,
        name="download",
    ),
    path(
        "attachments/<int:attachment_id>/download/",
        views.attachment_download_view,
        name="attachment_download",
    ),
    path(
        "attachments/<int:attachment_id>/preview/",
        views.attachment_preview_view,
        name="attachment_preview",
    ),
]
