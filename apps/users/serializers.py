"""
Users app serializers.

Validation is enforced at two layers:
- Serializer layer (HTTP 400)
- Model layer (clean() + full_clean()) for non-API code paths

This module provides:
- UserSerializer: create/update representation (write-capable)
- UserListSerializer: admin list representation
- UserDetailSerializer: profile + counters + small previews
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.projects.models import Project
from common.validators import validate_birth_date_min_age

User = get_user_model()


class UserProjectPreviewSerializer(serializers.ModelSerializer):
    """
    Minimal project representation embedded in /users/{id}/.

    Notes:
    - issues_count must be annotated in the queryset.
    """

    owner_username = serializers.CharField(source="author.username", read_only=True)
    issues_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Project
        fields = ("id", "name", "owner_username", "issues_count")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """
    Base serializer for creating/updating a user.

    Responsibilities:
    - Accept plaintext password (write-only) and hash via set_password()
    - Enforce birth_date business rules at the API boundary
    """

    email = serializers.EmailField(required=True, allow_blank=False)
    password = serializers.CharField(
        write_only=True,
        required=False,  # keep optional for update
        allow_blank=False,
        min_length=8,
        help_text="Plaintext password (write-only). Hashed before saving.",
    )

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
            "password",
        )
        read_only_fields = ("id",)

    def validate_birth_date(self, value) -> date:
        """Validate the birth_date field via shared project validator."""
        try:
            validate_birth_date_min_age(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Enforce password rules:
        - Create (no instance yet): password is required.
        - Update (instance exists): password is optional.
        """
        attrs = super().validate(attrs)

        is_create = self.instance is None
        if is_create:
            required_fields = ("username", "email", "birth_date", "password")
            missing = {
                field: "Ce champs est requis"
                for field in required_fields
                if not attrs.get(field)
            }

            if missing:
                raise serializers.ValidationError(missing)

        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        """
        Create a User instance via the model manager.

        Why:
        - Ensures Django's UserManager logic is applied
            (normalization, password handling).
        - Prevents bypassing manager-level invariants.
        - Keeps model validation via your overridden save() calling full_clean().
        """
        password = validated_data.pop("password")

        try:
            user = User.objects.create_user(password=password, **validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return user

    def update(self, instance: User, validated_data: dict[str, Any]) -> User:
        """Update a User instance with optional password hashing."""
        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        try:
            instance.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return instance


class UserListSerializer(serializers.ModelSerializer):
    """Admin list serializer for /users/."""

    projects_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "projects_count")
        read_only_fields = fields


class UserDetailSerializer(UserSerializer):
    """
    Detail serializer for /users/{id}/.

    Contains:
    - Profile fields (write-capable via UserSerializer)
    - Counters (annotated in UserViewSet.get_queryset)
    - Short previews for convenience
    """

    num_projects_owned = serializers.IntegerField(read_only=True)
    num_projects_added_as_contrib = serializers.IntegerField(read_only=True)

    owned_projects_preview = serializers.SerializerMethodField()
    contributed_projects_preview = serializers.SerializerMethodField()

    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + (
            "created_at",
            "updated_at",
            "num_projects_owned",
            "num_projects_added_as_contrib",
            "owned_projects_preview",
            "contributed_projects_preview",
        )

    @extend_schema_field(UserProjectPreviewSerializer(many=True))
    def get_owned_projects_preview(self, obj: User) -> list[dict[str, Any]]:
        """Return up to 5 recently updated projects owned by the user."""
        qs = (
            Project.objects.filter(author=obj)
            .select_related("author")
            .annotate(issues_count=Count("issues", distinct=True))
            .order_by("-updated_at")[:5]
        )
        return UserProjectPreviewSerializer(qs, many=True).data

    @extend_schema_field(UserProjectPreviewSerializer(many=True))
    def get_contributed_projects_preview(self, obj: User) -> list[dict[str, Any]]:
        """
        Return up to 5 recently updated projects where the user is a contributor.

        Owned projects are excluded to avoid duplication when the owner is also
        present in the contributors relation.
        """
        qs = (
            Project.objects.filter(contributors=obj)
            .exclude(author=obj)
            .select_related("author")
            .annotate(issues_count=Count("issues"))
            .order_by("-updated_at")[:5]
        )
        return UserProjectPreviewSerializer(qs, many=True).data
