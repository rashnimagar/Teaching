from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom user manager where email is the unique identifier
    for authentication instead of usernames, with lowercase normalization.
    """

    def normalize_email(self, email):
        """Normalize email address to lowercase."""
        email = super().normalize_email(email)
        return email.lower() if email else email

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("The Email field must be set"))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.TEACHER)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))
        if not password:
            raise ValueError(_("Superuser must have a password."))

        user = self.create_user(email, password, **extra_fields)
        try:
            from allauth.account.models import EmailAddress

            email_obj, created = EmailAddress.objects.get_or_create(
                user=user,
                email=user.email,
                defaults={"verified": True, "primary": True},
            )
            if not created and not email_obj.verified:
                email_obj.verified = True
                email_obj.save(update_fields=["verified"])
        except Exception:
            pass
        return user


class User(AbstractUser):
    """
    Custom User model with email-only authentication and role support.
    """

    class Role(models.TextChoices):
        STUDENT = "student", _("Student")
        TEACHER = "teacher", _("Teacher")

    username = None
    email = models.EmailField(_("email address"), unique=True)
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
    )
    terms_accepted_at = models.DateTimeField(
        _("terms accepted at"),
        null=True,
        blank=True,
        help_text=_("Timestamp when the user accepted Terms of Service on signup."),
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="unique_lower_email",
            ),
        ]

    def __str__(self):
        return self.email

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER
