from apps.accounts.permissions import is_teacher_user


def teacher_nav_context(request):
    """
    Supplies badge counts for the teacher sidebar navigation across all
    dashboard views. Catches database errors gracefully.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not is_teacher_user(user):
        return {}

    from apps.assignments.models import Submission
    from apps.courses.models import DownloadRequest, Enrollment

    try:
        pending_permissions = DownloadRequest.objects.filter(
            status=DownloadRequest.Status.PENDING
        ).count()
        pending_enrollments = Enrollment.objects.filter(
            status=Enrollment.Status.PENDING
        ).count()
        ungraded_submissions = Submission.objects.filter(
            grade__isnull=True,
            assignment__is_published=True,
            assignment__course__is_archived=False,
        ).count()

        return {
            "nav_pending_permissions_count": pending_permissions,
            "nav_pending_enrollments_count": pending_enrollments,
            "nav_ungraded_submissions_count": ungraded_submissions,
        }
    except Exception:
        return {
            "nav_pending_permissions_count": 0,
            "nav_pending_enrollments_count": 0,
            "nav_ungraded_submissions_count": 0,
        }
