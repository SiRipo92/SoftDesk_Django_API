"""
Projects app serializers.

- ProjectSerializer: CRUD for Project resources.
- ContributorReadSerializer: representation of project membership rows
    (read-only output).
- ContributorCreateSerializer: validates username/email lookup
    then creates a membership row.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from common.validators import validate_exactly_one_provided

from .models import Contributor, Project

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for Project CRUD."""

    # Read-only author info that exposes id + username
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
        read_only_fields = (
            "id",
            "author_id",
            "author_username",
            "created_at",
            "updated_at",
        )

    def create(self, validated_data: dict[str, Any]) -> Project:
        """
        Create a Project.

        Author is always the authenticated user (never provided by client).
        """
        request = self.context["request"]
        return Project.objects.create(author=request.user, **validated_data)


class ContributorReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for membership rows.

    Why ModelSerializer here?
    - This serializer represents an actual Contributor model instance.
    - Output fields are either model fields (id, created_at) or derived from relations.

    This is presentation / representation for:
    - listing contributors on a project
    - returning the created membership row after POST
    """

    # Contributor.user is a FK -> expose selected user info in a flattened shape
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    # Contributor.added_by is a FK -> expose who added the contributor
    added_by_id = serializers.IntegerField(source="added_by.id", read_only=True)
    added_by_username = serializers.CharField(
        source="added_by.username", read_only=True
    )

    class Meta:
        model = Contributor
        fields = (
            "id",
            "user_id",
            "user_username",
            "user_email",
            "added_by_id",
            "added_by_username",
            "created_at",
        )
        # This serializer is output-only: no writes expected from client
        read_only_fields = fields


class ContributorCreateSerializer(serializers.Serializer):
    """
    Input-only serializer for adding a contributor to a project.

    IMPORTANT: Why NOT ModelSerializer?
    - ModelSerializer is intended when the client payload maps to model fields.
      Example: { "user": 12, "project": 3, "added_by": 7 } (direct Contributor fields).
    - Here, the client does NOT send Contributor model fields.
      The client sends lookup keys: { "username": "..." } OR { "email": "..." }
      These are NOT fields on the Contributor model.
    - serializers.Serializer validates the lookup input,
      resolves a User from the database,
      and then creates the Contributor row server-side.

    Context requirements (provided by the view):
    - context["request"]
    - context["project"]
    """

    # Lookup keys sent by client (not model fields)
    username = serializers.CharField(required=False, allow_blank=False)
    email = serializers.EmailField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Validate that exactly one lookup key is provided and resolve the target user.

        DB lookups belong here because:
         - "does this username/email exist?" is a database concern
         - "is this user already a contributor?" is a database constraint check
        """
        username: str | None = attrs.get("username")
        email: str | None = attrs.get("email")

        # Enforce: exactly one of username/email must be provided
        try:
            validate_exactly_one_provided(username=username, email=email)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        # Resolve target user (DB lookup)
        if username:
            user = User.objects.filter(username=username).first()
        else:
            user = User.objects.filter(email=email).first()

        if not user:
            raise serializers.ValidationError("Utilisateur introuvable.")

        # Project is injected via context (never trusted from client payload)
        project: Project = self.context["project"]

        # Prevent duplicates (DB lookup)
        if Contributor.objects.filter(project=project, user=user).exists():
            raise serializers.ValidationError("Cet utilisateur est déjà contributeur.")

        # Carry resolved objects forward to create()
        attrs["resolved_user"] = user
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Contributor:
        """
        Create a Contributor membership row.

        Inputs come indirectly:
        - validate() injects `resolved_user`
        - project comes from serializer context
        - added_by is always the authenticated user (request.user)

        We do not accept these sensitive fields from the client.
        """
        request = self.context["request"]
        project: Project = self.context["project"]
        user = validated_data["resolved_user"]

        return Contributor.objects.create(
            project=project,
            user=user,
            added_by=request.user,
        )
