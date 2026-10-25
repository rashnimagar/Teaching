from django.urls import path

from apps.courses import views, views_materials

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
    path("<slug:course_slug>/materials/", views_materials.course_materials_view, name="materials"),
    path(
        "<slug:course_slug>/materials/<int:item_id>/request/",
        views_materials.material_request_download_view,
        name="material_request",
    ),
    path(
        "<slug:course_slug>/materials/<int:item_id>/cancel/",
        views_materials.material_cancel_request_view,
        name="material_cancel",
    ),
    path(
        "<slug:course_slug>/materials/<int:item_id>/download/",
        views_materials.material_download_view,
        name="material_download",
    ),
    path(
        "<slug:course_slug>/materials/<int:item_id>/preview/",
        views_materials.material_preview_view,
        name="material_preview",
    ),
]
