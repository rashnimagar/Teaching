from django.urls import path

from apps.dashboard import (
    views,
    views_assignments,
    views_courses,
    views_enrollments,
    views_lessons,
    views_materials,
    views_permissions,
    views_reports,
    views_settings,
    views_students,
    views_submissions,
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
    # Enrollments (Phase 7B)
    path("teacher/enrollments/", views_enrollments.teacher_enrollments_list_view, name="teacher_enrollments"),
    path("teacher/enrollments/action/<int:enrollment_id>/", views_enrollments.teacher_enrollment_action_view, name="teacher_enrollment_action"),
    path("teacher/enrollments/bulk/", views_enrollments.teacher_enrollments_bulk_action_view, name="teacher_enrollments_bulk_action"),
    path("teacher/enrollments/manual/", views_enrollments.teacher_enrollment_manual_view, name="teacher_enrollment_manual"),
    # Submissions & Grading (Phase 7B)
    path("teacher/submissions/", views_submissions.teacher_submissions_list_view, name="teacher_submissions"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/submissions/", views_submissions.teacher_course_assignment_submissions_view, name="teacher_course_assignment_submissions"),
    path("teacher/courses/<slug:slug>/assignments/<int:assignment_id>/missed/", views_submissions.teacher_missed_deadlines_view, name="teacher_missed_deadlines"),
    path("teacher/submissions/<int:submission_id>/grade/", views_submissions.teacher_submission_grade_view, name="teacher_submission_grade"),
    path("teacher/submissions/<int:submission_id>/unlock/", views_submissions.teacher_submission_unlock_view, name="teacher_submission_unlock"),
    # Students Directory (Phase 7B)
    path("teacher/students/", views_students.teacher_students_list_view, name="teacher_students"),
    path("teacher/students/<int:student_id>/", views_students.teacher_student_detail_view, name="teacher_student_detail"),
    path("teacher/students/<int:student_id>/toggle-active/", views_students.teacher_student_toggle_active_view, name="teacher_student_toggle_active"),
    # Exports & Reports (Phase 7B)
    path("teacher/courses/<slug:slug>/exports/grades/", views_reports.teacher_course_grades_export_view, name="teacher_course_grades_export"),
    path("teacher/courses/<slug:slug>/exports/progress/", views_reports.teacher_course_progress_export_view, name="teacher_course_progress_export"),
    # Materials Management (Phase 7C)
    path("teacher/materials/", views_materials.teacher_materials_course_picker_view, name="teacher_materials"),
    path("teacher/courses/<slug:slug>/materials/", views_materials.teacher_materials_list_view, name="teacher_course_materials"),
    path("teacher/courses/<slug:slug>/materials/create/", views_materials.teacher_material_create_view, name="teacher_material_create"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/edit/", views_materials.teacher_material_edit_view, name="teacher_material_edit"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/toggle-publish/", views_materials.teacher_material_toggle_publish_view, name="teacher_material_toggle_publish"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/archive/", views_materials.teacher_material_archive_view, name="teacher_material_archive"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/delete/", views_materials.teacher_material_delete_view, name="teacher_material_delete"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/create/", views_materials.teacher_material_item_create_view, name="teacher_material_item_create"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/<int:item_id>/edit/", views_materials.teacher_material_item_edit_view, name="teacher_material_item_edit"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/<int:item_id>/toggle-publish/", views_materials.teacher_material_item_toggle_publish_view, name="teacher_material_item_toggle_publish"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/<int:item_id>/delete/", views_materials.teacher_material_item_delete_view, name="teacher_material_item_delete"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/<int:item_id>/reorder/", views_materials.teacher_material_item_reorder_view, name="teacher_material_item_reorder"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/<int:item_id>/policy/", views_materials.teacher_material_item_policy_view, name="teacher_material_item_policy"),
    path("teacher/courses/<slug:slug>/materials/<int:material_id>/items/<int:item_id>/history/", views_materials.teacher_material_item_history_view, name="teacher_material_item_history"),
    # Site Settings & FAQ (Phase 7C)
    path("teacher/settings/", views_settings.teacher_settings_view, name="teacher_settings"),
    path("teacher/faqs/", views_settings.teacher_faqs_list_view, name="teacher_faqs"),
    path("teacher/faqs/create/", views_settings.teacher_faq_create_view, name="teacher_faq_create"),
    path("teacher/faqs/<int:faq_id>/edit/", views_settings.teacher_faq_edit_view, name="teacher_faq_edit"),
    path("teacher/faqs/<int:faq_id>/toggle-publish/", views_settings.teacher_faq_toggle_publish_view, name="teacher_faq_toggle_publish"),
    path("teacher/faqs/<int:faq_id>/reorder/", views_settings.teacher_faq_reorder_view, name="teacher_faq_reorder"),
    path("teacher/faqs/<int:faq_id>/delete/", views_settings.teacher_faq_delete_view, name="teacher_faq_delete"),
]
