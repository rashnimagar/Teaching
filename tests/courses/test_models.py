from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.courses.models import Course, Enrollment, Lesson, LessonProgress

User = get_user_model()


@pytest.fixture
def course_factory(db):
    def create_course(**kwargs):
        defaults = {
            "title": "Sample Course",
            "slug": "sample-course",
            "is_free": True,
            "is_published": True,
        }
        defaults.update(kwargs)
        return Course.objects.create(**defaults)

    return create_course


@pytest.fixture
def lesson_factory(db, course_factory):
    def create_lesson(**kwargs):
        if "course" not in kwargs:
            kwargs["course"] = course_factory()
        defaults = {
            "title": "Lesson 1",
            "order": 1,
            "video_provider": Lesson.VideoProvider.YOUTUBE,
            "video_id": "dQw4w9WgXcQ",
        }
        defaults.update(kwargs)
        return Lesson.objects.create(**defaults)

    return create_lesson


@pytest.mark.django_db
class TestCourseModel:
    def test_free_course_without_price_succeeds(self, course_factory):
        course = course_factory(is_free=True, price=None)
        assert course.pk is not None
        assert course.is_archived is False
        assert course.is_featured is False

    def test_paid_course_without_price_raises_integrity_error(self, db):
        with pytest.raises(IntegrityError):
            Course.objects.create(
                title="Paid Course",
                slug="paid-course",
                is_free=False,
                price=None,
            )

    def test_paid_course_with_zero_or_negative_price_raises_integrity_error(self, db):
        with pytest.raises(IntegrityError):
            Course.objects.create(
                title="Paid Course",
                slug="paid-course-zero",
                is_free=False,
                price=Decimal("0.00"),
            )

    def test_course_clean_validates_paid_price(self):
        course = Course(
            title="Paid Course",
            slug="paid-course",
            is_free=False,
            price=None,
        )
        with pytest.raises(ValidationError, match="Paid courses must specify a positive price."):
            course.clean()

    def test_course_slug_uniqueness(self, course_factory):
        course_factory(slug="duplicate-slug")
        with pytest.raises(IntegrityError):
            course_factory(slug="duplicate-slug", title="Another Course")


@pytest.mark.django_db
class TestLessonModel:
    def test_lesson_creation_and_ordering(self, course_factory, lesson_factory):
        course = course_factory()
        lesson_2 = lesson_factory(course=course, order=2, title="Second")
        lesson_1 = lesson_factory(course=course, order=1, title="First")

        lessons = list(course.lessons.all())
        assert lessons == [lesson_1, lesson_2]

    def test_lesson_video_id_validation_youtube(self, course_factory):
        course = course_factory()
        # Invalid YouTube ID (length != 11)
        invalid_lesson = Lesson(
            course=course,
            title="Bad Video",
            video_provider=Lesson.VideoProvider.YOUTUBE,
            video_id="short",
        )
        with pytest.raises(
            ValidationError, match="YouTube video ID must be an 11-character identifier."
        ):
            invalid_lesson.clean()


@pytest.mark.django_db
class TestEnrollmentModel:
    def test_enrollment_uniqueness(self, user_factory, course_factory):
        student = user_factory()
        course = course_factory()
        Enrollment.objects.create(student=student, course=course)

        with pytest.raises(IntegrityError):
            Enrollment.objects.create(student=student, course=course)

    def test_cannot_delete_course_with_active_enrollments(self, user_factory, course_factory):
        student = user_factory()
        course = course_factory()
        Enrollment.objects.create(student=student, course=course)

        with pytest.raises(ProtectedError):
            course.delete()


@pytest.mark.django_db
class TestLessonProgressModel:
    def test_lesson_progress_uniqueness(self, user_factory, lesson_factory):
        student = user_factory()
        lesson = lesson_factory()
        LessonProgress.objects.create(student=student, lesson=lesson, last_position_seconds=120)

        with pytest.raises(IntegrityError):
            LessonProgress.objects.create(student=student, lesson=lesson)
