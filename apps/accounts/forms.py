from allauth.account.forms import LoginForm, SignupForm
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    """
    A form for creating new users in admin without a username field.
    """

    class Meta:
        model = User
        fields = ("email", "role")

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email:
            return email.lower()
        return email


class CustomUserChangeForm(UserChangeForm):
    """
    A form for updating users in admin.
    """

    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "is_staff",
            "is_superuser",
            "terms_accepted_at",
            "groups",
            "user_permissions",
        )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email:
            return email.lower()
        return email


class CustomSignupForm(SignupForm):
    """
    Custom registration form collecting name, email, strong password,
    and explicit terms agreement, while protecting against honeypot spam
    and privilege escalation.
    """

    first_name = forms.CharField(
        max_length=150,
        required=True,
        label=_("First name"),
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. Roshan or राम",
                "autocomplete": "given-name",
            }
        ),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label=_("Last name"),
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. Adhikari or अधिकारी",
                "autocomplete": "family-name",
            }
        ),
    )
    terms = forms.BooleanField(
        required=True,
        label=_("I agree to the Terms of Service and Privacy Policy"),
        error_messages={
            "required": _(
                "You must agree to the Terms of Service and Privacy Policy to create an account."
            ),
        },
    )

    field_order = [
        "first_name",
        "last_name",
        "email",
        "password1",
        "terms",
        "organization_code",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "first_name" in self.fields:
            self.fields["first_name"].widget.attrs.update(
                {
                    "placeholder": "e.g. Roshan or राम",
                    "autocomplete": "given-name",
                    "autocapitalize": "words",
                }
            )
        if "last_name" in self.fields:
            self.fields["last_name"].widget.attrs.update(
                {
                    "placeholder": "e.g. Adhikari or अधिकारी",
                    "autocomplete": "family-name",
                    "autocapitalize": "words",
                }
            )
        if "email" in self.fields:
            self.fields["email"].widget.attrs.update(
                {
                    "placeholder": "you@example.com",
                    "autocomplete": "email",
                    "autocapitalize": "none",
                    "inputmode": "email",
                    "spellcheck": "false",
                }
            )
        if "password1" in self.fields:
            self.fields["password1"].widget.attrs.update(
                {
                    "placeholder": "At least 10 characters or a passphrase",
                    "autocomplete": "new-password",
                    "autocapitalize": "none",
                    "spellcheck": "false",
                }
            )
        if "organization_code" in self.fields:
            self.fields["organization_code"].widget.attrs.pop("style", None)
            self.fields["organization_code"].widget.attrs.update(
                {
                    "class": "absolute -left-[9999px] -top-[9999px] opacity-0 pointer-events-none h-0 w-0 overflow-hidden",
                    "tabindex": "-1",
                    "autocomplete": "off",
                    "aria-hidden": "true",
                }
            )

    def clean_organization_code(self):
        # Additional defensive check on the honeypot field
        val = self.cleaned_data.get("organization_code")
        if val:
            raise forms.ValidationError(_("Invalid submission."))
        return val

    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data.get("first_name", "").strip()
        user.last_name = self.cleaned_data.get("last_name", "").strip()
        user.role = User.Role.STUDENT
        user.is_staff = False
        user.is_superuser = False
        user.terms_accepted_at = timezone.now()
        user.save()
        return user


class CustomLoginForm(LoginForm):
    """
    Custom login form styling email, password, and remember me fields.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "login" in self.fields:
            self.fields["login"].widget.attrs.update(
                {
                    "placeholder": "you@example.com",
                    "autocomplete": "email",
                    "autocapitalize": "none",
                    "inputmode": "email",
                    "spellcheck": "false",
                }
            )
        if "password" in self.fields:
            self.fields["password"].widget.attrs.update(
                {
                    "placeholder": "••••••••••••",
                    "autocomplete": "current-password",
                    "autocapitalize": "none",
                    "spellcheck": "false",
                }
            )
