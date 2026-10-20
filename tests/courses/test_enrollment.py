from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.courses.models import Course, Enrollment

User = get_user_model()


@pytest.fixture
def student_user(user_factory):
    return user_factory(email="student.test@example.com", role=User.Role.STUDENT)


@pytest.fixture
def free_course(db):
    return Course.objects.create(
        title="Python for Beginners",
        slug="python-beginners",
        is_published=True,
        is_free=True,
        requires_approval=False,
    )


@pytest.fixture
def approval_course(db):
    return Course.objects.create(
        title="Selective Cohort Track",
        slug="selective-cohort",
        is_published=True,
        is_free=True,
        requires_approval=True,
    )


@pytest.fixture
def paid_course(db):
    return Course.objects.create(
        title="Fullstack Django Mastery",
        slug="fullstack-django-mastery",
        is_published=True,
        is_free=False,
        price=Decimal("9999.00"),
        currency="NPR",
    )


@pytest.mark.django_db
class TestEnrollmentFlow:
    def test_anonymous_user_redirected_to_login(self, client: Client, free_course):
        url = reverse("courses:enroll", kwargs={"slug": free_course.slug})
        resp = client.post(url)
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url
        assert f"next={url}" in resp.url
        assert Enrollment.objects.count() == 0

    def test_free_course_instant_enrollment_creates_active_status(
        self, client: Client, student_user, free_course
    ):
        client.force_login(student_user)
        url = reverse("courses:enroll", kwargs={"slug": free_course.slug})
        resp = client.post(url, follow=True)
        assert resp.status_code == 200

        enrollment = Enrollment.objects.get(student=student_user, course=free_course)
        assert enrollment.status == Enrollment.Status.ACTIVE
        assert enrollment.source == Enrollment.Source.FREE

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        assert any("successfully enrolled" in m.lower() for m in messages)

    def test_approval_course_enrollment_creates_pending_status(
        self, client: Client, student_user, approval_course
    ):
        client.force_login(student_user)
        url = reverse("courses:enroll", kwargs={"slug": approval_course.slug})
        resp = client.post(url, follow=True)
        assert resp.status_code == 200

        enrollment = Enrollment.objects.get(student=student_user, course=approval_course)
        assert enrollment.status == Enrollment.Status.PENDING
        assert enrollment.source == Enrollment.Source.FREE

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        assert any("submitted for review" in m.lower() for m in messages)

    def test_paid_course_enrollment_post_is_blocked(
        self, client: Client, student_user, paid_course
    ):
        client.force_login(student_user)
        url = reverse("courses:enroll", kwargs={"slug": paid_course.slug})
        resp = client.post(url, follow=True)
        assert resp.status_code == 200

        # No enrollment should be created for paid courses via self-serve endpoint
        assert not Enrollment.objects.filter(student=student_user, course=paid_course).exists()

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        assert any("enrollment opens soon" in m.lower() for m in messages)

    def test_revoked_user_cannot_re_enroll(self, client: Client, student_user, free_course):
        # Existing revoked enrollment
        Enrollment.objects.create(
            student=student_user,
            course=free_course,
            status=Enrollment.Status.REVOKED,
            source=Enrollment.Source.FREE,
        )

        client.force_login(student_user)

        # Detail page should show revoked alert and no enroll button
        detail_resp = client.get(reverse("courses:detail", kwargs={"slug": free_course.slug}))
        assert detail_resp.status_code == 200
        content = detail_resp.content.decode("utf-8")
        assert "Access removed, please contact the teacher." in content
        assert "Enroll for Free" not in content

        # Direct POST attempt must be rejected
        enroll_url = reverse("courses:enroll", kwargs={"slug": free_course.slug})
        post_resp = client.post(enroll_url, follow=True)
        assert post_resp.status_code == 200

        messages = [m.message for m in get_messages(post_resp.wsgi_request)]
        assert any("access removed, please contact the teacher" in m.lower() for m in messages)

        # Status remains REVOKED
        enrollment = Enrollment.objects.get(student=student_user, course=free_course)
        assert enrollment.status == Enrollment.Status.REVOKED

    def test_double_submit_creates_exactly_one_row(self, client: Client, student_user, free_course):
        client.force_login(student_user)
        url = reverse("courses:enroll", kwargs={"slug": free_course.slug})

        # First submit
        resp1 = client.post(url)
        assert resp1.status_code == 302
        assert Enrollment.objects.filter(student=student_user, course=free_course).count() == 1

        # Second submit immediately after
        resp2 = client.post(url, follow=True)
        assert resp2.status_code == 200
        assert Enrollment.objects.filter(student=student_user, course=free_course).count() == 1

        messages = [m.message for m in get_messages(resp2.wsgi_request)]
        assert any("already enrolled" in m.lower() for m in messages)
