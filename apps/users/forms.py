from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    """
    Admin form used on the *Add user* page.

    Why this is needed:
    - Your model requires email + birth_date (full_clean() enforces it).
    - Django's default admin add form only includes username/password.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "email",
            "birth_date",
            "can_be_contacted",
            "can_data_be_shared",
        )


class CustomUserChangeForm(UserChangeForm):
    """
    Admin form used on the *Change user* page.
    """

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"
