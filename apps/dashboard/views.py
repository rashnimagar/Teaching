from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.accounts.permissions import teacher_required


@login_required
def student_dashboard(request):
    """
    Placeholder student portal showing enrolled courses and learning progress.
    """
    return render(request, "dashboard/student_dashboard.html")


@teacher_required
def teacher_dashboard(request):
    """
    Placeholder teacher portal for managing content, enrollments, and grading.
    """
    return render(request, "dashboard/teacher_dashboard.html")
