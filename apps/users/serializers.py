"""
Users app serializers.

Enforces business rules at the API boundary (friendly 400 errors),
while the model enforces the same rules at save-time (harder to bypass).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.projects.models import Project
from common.validators import validate_birth_date_min_age

User = get_user_model()


class UserProjectSummarySerializer(serializers.ModelSerializer):
    """
    Small project representation to embed inside User detail responses.

    Purpose is for Admin-Listing of Users
    """

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "description",
            "project_type",
            "author_id",
            "author_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """
    Base serializer for creating/updating a user.

    Responsibilities:
    - Expose the API representation of a User.
    - Accept a plaintext password (write-only) and hash it via set_password().
    - Enforce business rules for birth_date at the API boundary.
    - Convert model-level ValidationError into DRF ValidationError (HTTP 400).

    Notes:
    - The model also enforces validation via clean() + save(full_clean()).
      This serializer adds user-friendly validation errors early in the request.
    - Adds summary counters :
        - num_projects_owned: projects where user is the author.
        - num_projects_added_as_contrib: projects where user is a contributor
            but NOT the author (i.e., they were added to someone else's project).
    """

    password = serializers.CharField(
        write_only=True,
        required=False,
        min_length=8,
        help_text="Plaintext password (write-only). Will be hashed before saving.",
    )

    class Meta:
        """Meta configuration for the UserSerializer."""

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

    def validate_birth_date(self, value):
        """
        Validate the birth_date field.

        The rule is delegated to a shared validator used across the project.

        Args:
            value (date): The incoming birth date.

        Returns:
            date: The validated birth date.

        Raises:
            serializers.ValidationError: If the birth date violates business rules
            (e.g., user too young, date in the future, etc.).
        """
        try:
            validate_birth_date_min_age(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def create(self, validated_data: dict[str, Any]):
        """
        Create a User instance.

        - Pops "password" from validated_data
        - Hashes it using set_password()
        - Saves the user (model will run full_clean in save())

        Args:
            validated_data (dict[str, Any]): Incoming validated fields.

        Returns:
            User: The newly created user.

        Raises:
            serializers.ValidationError: If model-level validation fails.
        """
        password = validated_data.pop("password", None)
        user = User(**validated_data)

        if password:
            user.set_password(password)

        try:
            user.save()
        except DjangoValidationError as exc:
            # Preserve field-level error mapping from Django (message_dict).
            raise serializers.ValidationError(exc.message_dict) from exc

        return user

    def update(self, instance: User, validated_data: dict[str, Any]):
        """
        Update a User instance.

        - Updates provided attributes via setattr()
        - Hashes password if provided
        - Saves the instance (model will run full_clean in save())

        Args:
            instance (User): The user instance to update.
            validated_data (dict[str, Any]): Incoming validated fields.

        Returns:
            User: The updated user.

        Raises:
            serializers.ValidationError: If model-level validation fails.
        """
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
    """
    Admin list serializer.

    Goal:
    - Keep it light.
    - Include a computed projects_count
        (number of projects where the user is contributor).
    """

    projects_count = serializers.IntegerField(read_only=True)
    num_projects_owned = serializers.IntegerField(read_only=True)
    num_projects_added_as_contrib = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "projects_count",
            "num_projects_owned",
            "num_projects_added_as_contrib",
        )
        read_only_fields = fields


class UserDetailSerializer(UserSerializer):
    """
    Detail serializer for /users/{id}/

    Adds:
    - owned_projects: projects authored by this user
    - contributed_projects: projects where user is a contributor but not the author
    - summary counters
    """

    owned_projects = serializers.SerializerMethodField()
    contributed_projects = serializers.SerializerMethodField()

    num_projects_owned = serializers.IntegerField(read_only=True)
    num_projects_added_as_contrib = serializers.IntegerField(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + (
            "num_projects_owned",
            "num_projects_added_as_contrib",
            "owned_projects",
            "contributed_projects",
        )

    def get_owned_projects(self, obj: User):
        """
        Projects where the user is the author (owner).

        Why this is separate:
        - It answers “what did this user create/own?”
        """
        qs = (
            Project.objects.filter(author=obj)
            .select_related("author")
            .order_by("-updated_at")
        )
        return UserProjectSummarySerializer(qs, many=True).data

    def get_contributed_projects(self, obj: User):
        """
        Projects where the user is a contributor but NOT the author.

        Why the exclude():
        - In this system the owner is also a contributor for visibility.
        - Without excluding owned projects, entries would be duplicated
            across both lists.
        """
        qs = (
            Project.objects.filter(contributors=obj)
            .exclude(author=obj)          # <-- prevents overlap with owned_projects
            .select_related("author")
            .distinct()
            .order_by("-updated_at")
        )
        return UserProjectSummarySerializer(qs, many=True).data
