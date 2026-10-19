from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

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
        fields = "__all__"

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email:
            return email.lower()
        return email
