from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

User = get_user_model()


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    list_display = (
        "id",
        "username",
        "email",
        "is_staff",
        "is_superuser",
        "created_at",
    )

    list_filter = ("is_staff", "is_superuser", "is_active")

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
