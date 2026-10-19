import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

User = get_user_model()


@pytest.mark.django_db
class TestUserManager:
    """Test custom UserManager creation, normalization, and constraints."""

    def test_create_user_normalizes_email_to_lowercase(self):
        user = User.objects.create_user(
            email="StUdEnT@ExAmPlE.cOm",
            password="secure-password-123",
        )
        assert user.email == "student@example.com"
        assert user.role == User.Role.STUDENT
        assert user.is_student is True
        assert user.is_teacher is False
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.check_password("secure-password-123") is True

    def test_create_user_without_email_raises_error(self):
        with pytest.raises(ValueError, match="The Email field must be set"):
            User.objects.create_user(email="")

    def test_create_superuser_success(self):
        admin = User.objects.create_superuser(
            email="admin@example.com",
            password="admin-password-123",
        )
        assert admin.email == "admin@example.com"
        assert admin.is_staff is True
        assert admin.is_superuser is True
        assert admin.role == User.Role.TEACHER
        assert admin.is_teacher is True

    def test_create_superuser_missing_password_raises_error(self):
        with pytest.raises(ValueError, match="Superuser must have a password."):
            User.objects.create_superuser(
                email="admin@example.com",
                password=None,
            )

    def test_email_case_insensitive_uniqueness(self):
        User.objects.create_user(
            email="testuser@example.com",
            password="password1",
        )
        # Attempting to create duplicate user with different casing
        with pytest.raises(IntegrityError):
            User.objects.create(
                email="TESTUSER@example.com",
                role=User.Role.STUDENT,
            )
