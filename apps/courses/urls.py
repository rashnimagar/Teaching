from django.urls import path

from apps.courses import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list_view, name="list"),
    path("<slug:slug>/", views.course_detail_view, name="detail"),
    path("<slug:slug>/enroll/", views.course_enroll_view, name="enroll"),
]
