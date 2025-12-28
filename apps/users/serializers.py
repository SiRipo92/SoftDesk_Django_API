"""
Users app serializers.

Enforces business rules at the API boundary (friendly 400 errors),
while the model enforces the same rules at save-time (harder to bypass).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from common.validators import validate_birth_date_min_age

User = get_user_model()


def drf_birth_date_validator(value: date) -> date:
    """
    DRF wrapper around the common birth_date rule.

    Args:
        value (date): Incoming birth_date value.

    Returns:
        date: Same value if valid.

    Raises:
        serializers.ValidationError: If invalid.
    """
    try:
        validate_birth_date_min_age(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc
    return value

class UserBaseSerializer(serializers.ModelSerializer):
    """
    Base serializer that centralizes shared User fields.
    """

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "birth_date",
            "can_be_contacted",
            "can_data_be_shared",
        )
        read_only_fields = ("id",)


class UserSignupSerializer(UserBaseSerializer):
    """
    Signup serializer: includes password and requires birth_date.
    """
    password = serializers.CharField(write_only=True, min_length=8)

    # Override birth_date field to enforce "required" + custom FR messages
    birth_date = serializers.DateField(
        required=True,
        allow_null=False,
        validators=[drf_birth_date_validator],
        error_messages={
            "required": "La date de naissance est requise.",
            "null": "La date de naissance ne peut pas être vide.",
            "invalid": "Format de date invalide (YYYY-MM-DD).",
        },
    )

    class Meta(UserBaseSerializer.Meta):
        """Base User Serializer Meta that ties together fields and password"""
        fields = UserBaseSerializer.Meta.fields + ("password",)

    def create(self, validated_data: dict[str, Any]):
        """Create a user with a hashed password (convert model errors to 400)."""
        password: str = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)

        try:
            user.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return user


class UserMeSerializer(UserBaseSerializer):
    """
    /users/me serializer: birth_date can be omitted on PATCH,
    but if provided it must be valid (and cannot be null).
    """

    birth_date = serializers.DateField(
        required=False,  # may omit on PATCH
        allow_null=False,  # cannot send explicit null
        validators=[drf_birth_date_validator],
        error_messages={
            "null": "La date de naissance ne peut pas être vide.",
            "invalid": "Format de date invalide (YYYY-MM-DD).",
        },
    )

    def update(self, instance, validated_data: dict[str, Any]):
        """Update user fields (convert model errors to 400)."""
        for attr, val in validated_data.items():
            setattr(instance, attr, val)

        try:
            instance.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return instance
