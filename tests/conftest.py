import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def user_factory(db):
    """Factory fixture for creating test users."""

    def create_user(**kwargs):
        email = kwargs.pop("email", "student@example.com")
        password = kwargs.pop("password", "TestPassword123!")
        return User.objects.create_user(email=email, password=password, **kwargs)

    return create_user
