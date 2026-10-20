from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("student/", views.student_dashboard, name="student"),
    path("teacher/", views.teacher_dashboard, name="teacher"),
]
