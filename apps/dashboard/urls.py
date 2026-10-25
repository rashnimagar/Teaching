from django.urls import path

from apps.dashboard import (
    views,
    views_assignments,
    views_courses,
    views_lessons,
    views_permissions,
)

app_name = "dashboard"

urlpatterns = [
    path("student/", views.student_dashboard, name="student"),
    path("teacher/", views.teacher_dashboard, name="teacher"),
    # Permissions and Download Requests Queue (Existing)
    path("teacher/permissions/", views_permissions.teacher_permissions_view, name="teacher_permissions"),
    path("teacher/permissions/action/<int:request_id>/", views_permissions.teacher_permission_action_view, name="teacher_permission_action"),
    path("teacher/permissions/bulk/", views_permissions.teacher_permissions_bulk_action_view, name="teacher_permissions_bulk_action"),
    path("teacher/permissions/approve-all/<int:item_id>/", views_permissions.teacher_approve_for_all_view, name="teacher_approve_for_all"),
    path("teacher/permissions/history/<int:item_id>/", views_permissions.teacher_download_history_view, name="teacher_download_history"),
    # Courses
    path("teacher/courses/", views_courses.teacher_courses_list_view, name="teacher_courses"),
    path("teacher/courses/create/", views_courses.teacher_course_create_view, name="teacher_course_create"),
    path("teacher/courses/<slug:slug>/edit/", views_courses.teacher_course_edit_view, name="teacher_course_edit"),
    path("teacher/courses/<slug:slug>/archive/", views_courses.teacher_course_archive_view, name="teacher_course_archive"),
    # Lessons
    path("teacher/courses/<slug:slug>/lessons/", views_lessons.teacher_lessons_list_view, name="teacher_lessons"),
    path("teacher/courses/<slug:slug>/lessons/", views_lessons.teacher_lessons_list_view, name="teacher_course_lessons"),
    path("teacher/courses/<slug:slug>/lessons/create/", views_lessons.teacher_lesson_create_view, name="teacher_lesson_create"),
    path("teacher/courses/<slug:slug>/lessons/create/", views_lessons.teacher_lesson_create_view, name="teacher_course_lesson_create"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/edit/", views_lessons.teacher_lesson_edit_view, name="teacher_lesson_edit"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/edit/", views_lessons.teacher_lesson_edit_view, name="teacher_course_lesson_edit"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/toggle-publish/", views_lessons.teacher_lesson_toggle_publish_view, name="teacher_lesson_toggle_publish"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/toggle-publish/", views_lessons.teacher_lesson_toggle_publish_view, name="teacher_course_lesson_toggle_publish"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/reorder/", views_lessons.teacher_lesson_reorder_view, name="teacher_lesson_reorder"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/reorder/", views_lessons.teacher_lesson_reorder_view, name="teacher_course_lesson_reorder"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/delete/", views_lessons.teacher_lesson_delete_view, name="teacher_lesson_delete"),
    path("teacher/courses/<slug:slug>/lessons/<int:lesson_id>/delete/", views_lessons.teacher_lesson_delete_view, name="teacher_course_lesson_delete"),
    # Assignments
    path("teacher/courses/<slug:slug>/assignments/", views_assignments.teacher_assignments_list_view, name="teacher_assignments"),
    path("teacher/courses/<slug:slug>/assignments/", views_assignments.teacher_assignments_list_view, name="teacher_course_assignments"),
    path("teacher/courses/<slug:slug>/assignments/create/", views_assignments.teacher_assignment_create_view, name="teacher_assignment_create"),
    path("teacher/courses/<slug:slug>/assignments/create/", views_assignments.teacher_assignment_create_view, name="teacher_course_assignment_create"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/edit/", views_assignments.teacher_assignment_edit_view, name="teacher_assignment_edit"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/edit/", views_assignments.teacher_assignment_edit_view, name="teacher_course_assignment_edit"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/toggle-publish/", views_assignments.teacher_assignment_toggle_publish_view, name="teacher_assignment_toggle_publish"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/toggle-publish/", views_assignments.teacher_assignment_toggle_publish_view, name="teacher_course_assignment_toggle_publish"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/delete/", views_assignments.teacher_assignment_delete_view, name="teacher_assignment_delete"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/delete/", views_assignments.teacher_assignment_delete_view, name="teacher_course_assignment_delete"),
]
