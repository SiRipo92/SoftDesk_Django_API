from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserChangeForm, CustomUserCreationForm

User = get_user_model()


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    # IMPORTANT: use the custom forms
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm

    list_display = (
        "id",
        "username",
        "email",
        "is_staff",
        "is_superuser",
        "created_at",
    )
    list_filter = ("is_staff", "is_superuser", "is_active")
    ordering = ("id",)
    search_fields = ("username", "email")

    # Edit user page (change form)
    fieldsets = UserAdmin.fieldsets + (
        (
            "RGPD",
            {
                "fields": (
                    "birth_date",
                    "can_be_contacted",
                    "can_data_be_shared",
                )
            },
        ),
    )

    # Add user page (creation form)
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "birth_date",
                    "password1",
                    "password2",
                    "can_be_contacted",
                    "can_data_be_shared",
                ),
            },
        ),
    )
