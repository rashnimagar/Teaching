from functools import wraps

from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


class TeacherRequiredMixin(UserPassesTestMixin):
    """
    CBV mixin that enforces that the user is authenticated and possesses
    teacher or staff status.
    """

    def test_func(self) -> bool:
        user = self.request.user
        return bool(user.is_authenticated and (user.is_teacher or user.is_staff))


def teacher_required(view_func):
    """
    Decorator for views that checks that the user is logged in and is a teacher or staff member.
    Unauthenticated users are redirected to login; unauthorized students receive a 403.
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("account_login")
        if not (request.user.is_teacher or request.user.is_staff):
            raise PermissionDenied("You do not have permission to access the teacher dashboard.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
