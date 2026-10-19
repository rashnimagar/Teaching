import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.assignments.models import Assignment, Submission
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress

User = get_user_model()


@pytest.mark.django_db
class TestSeedDemoCommand:
    def test_seed_demo_refuses_to_run_when_debug_is_false(self, settings):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="Refusing to run seed_demo: DEBUG is False."):
            call_command("seed_demo")

    def test_seed_demo_populates_data_and_is_idempotent(self, settings):
        settings.DEBUG = True

        # First run
        call_command("seed_demo")

        assert Course.objects.count() == 2
        assert Lesson.objects.count() == 5
        assert Enrollment.objects.count() == 2
        assert LessonProgress.objects.count() == 1
        assert Assignment.objects.count() == 2
        assert Submission.objects.count() == 2

        # Check users have unusable passwords
        for email in ["teacher@example.com", "student1@example.com", "student2@example.com"]:
            user = User.objects.get(email=email)
            assert user.has_usable_password() is False

        # Check student1 submission is on-time and student2 submission is late
        sub1 = Submission.objects.get(student__email="student1@example.com")
        assert sub1.is_late is False
        assert sub1.grade is not None

        sub2 = Submission.objects.get(student__email="student2@example.com")
        assert sub2.is_late is True
        assert sub2.grade is None

        # Second run should succeed without duplicate integrity errors (idempotent)
        call_command("seed_demo")

        assert Course.objects.count() == 2
        assert Lesson.objects.count() == 5
        assert Enrollment.objects.count() == 2
        assert Submission.objects.count() == 2
