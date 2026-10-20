from django.urls import path

from apps.courses import views

app_name = "learn"

urlpatterns = [
    path("<slug:course_slug>/", views.course_learn_redirect_view, name="course"),
    path("<slug:course_slug>/<int:lesson_id>/", views.lesson_learn_view, name="lesson"),
    path(
        "<slug:course_slug>/<int:lesson_id>/toggle-complete/",
        views.lesson_toggle_complete_view,
        name="toggle_complete",
    ),
    path(
        "<slug:course_slug>/<int:lesson_id>/playback-position/",
        views.lesson_playback_position_view,
        name="playback_position",
    ),
]
