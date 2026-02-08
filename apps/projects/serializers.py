"""
Projects app serializers.

- ProjectListSerializer: project list output (includes contributors_count).
- ProjectDetailSerializer: project detail output (includes contributors list).
- ContributorReadSerializer: representation of membership rows (Contributor model).
- ContributorCreateSerializer: validates username/email lookup then creates membership.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count
from rest_framework import serializers

from apps.issues.serializers import IssuePreviewInProjectSerializer
from common.validators import validate_exactly_one_provided

from .models import Contributor, Project

User = get_user_model()


ISSUES_PREVIEW_LIMIT = 5

# -------------------------------------------------------------
# Project Serializers (Differentiates between fields in List & Detail)
# -------------------------------------------------------------


class ProjectWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for creating/updating projects.

    Author source:
    - defaults to request.user
    - can be overridden by context["author"] for admin flows
    """

    class Meta:
        model = Project
        fields = (
            "name",
            "description",
            "project_type",
        )

    def create(self, validated_data: dict[str, Any]) -> Project:
        """
        Create a project and ensure the owner is also a contributor.

        Notes:
        - `author` can be overridden by a view
        (ex: admin creating under /users/{id}/projects/).
        - The Contributor.added_by field tracks the actor
        who created the membership row.
        """
        request = self.context["request"]

        # Allow views to override author (ex: /users/{id}/projects/ as admin)
        author = self.context.get("author", request.user)

        # Create project
        project = Project.objects.create(author=author, **validated_data)

        # Ensure the author is also a contributor for visibility.
        # added_by tracks who created the membership row
        # (admin action remains traceable).
        Contributor.objects.get_or_create(
            project=project,
            user=author,
            # Actor attribution: admin action stays traceable.
            defaults={"added_by": request.user},
        )

        return project


class ProjectListSerializer(serializers.ModelSerializer):
    """
    Serializer for Project list views.

    Output goal:
    - Keep list responses light.
    - Provide contributors_count (excluding the owner).
    - Provide issues_count (integer only).
    """

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    contributors_count = serializers.IntegerField(read_only=True)
    issues_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "project_type",
            "author_id",
            "author_username",
            "contributors_count",
            "issues_count",
        )
        read_only_fields = fields


class ProjectDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for Project detail views.

    Output goal:
    - Show contributors as a list of membership rows excluding the owner.
    - Each row includes contributor identity + who added them.
    - We intentionally do NOT show created_at for contributors (per your need).
    """

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    contributors = serializers.SerializerMethodField()

    # Total issues count (comes from ProjectViewSet.get_queryset() annotation)
    issues_count = serializers.IntegerField(read_only=True)

    # Lightweight preview (last N issues only)
    issues_preview = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "description",
            "project_type",
            "author_id",
            "author_username",
            "contributors",
            "issues_count",
            "issues_preview",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_contributors(self, obj: Project) -> list[dict[str, Any]]:
        """
        Build the contributors list from Contributor membership rows.

        We read from obj.memberships (Contributor join table) because:
        - It contains added_by (who added the contributor).
        - It links to the user (contributor) for username/email.

        Owner exclusion:
        - The owner is always a contributor in DB for visibility.
        - We hide the owner from the contributors list in the API output.
        """
        memberships = (
            obj.memberships.select_related("user", "added_by")
            .exclude(user_id=obj.author_id)
            .order_by("user__username")
        )
        return ContributorReadSerializer(memberships, many=True).data

    def get_issues_preview(self, obj: Project) -> list[dict[str, Any]]:
        """
        Return only the most recent issues (preview), NOT the full issue list.

        Ordering uses updated_at, but the payload does not expose timestamps.
        """
        qs = (
            obj.issues.all()
            .only("id", "title")
            .prefetch_related("assignee_links")
            .annotate(
                assignees_count=Count("assignee_links__user", distinct=True),
                comments_count=Count("comments", distinct=True),
            )
            .order_by("-updated_at", "-id")[:ISSUES_PREVIEW_LIMIT]
        )
        return IssuePreviewInProjectSerializer(qs, many=True, context=self.context).data


# -------------------------------------------------------------
# Contributor Serializers for Reading and Writing
# -------------------------------------------------------------


class ContributorReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for membership rows.

    This serializer represents an actual Contributor model instance.
    Output fields are either model fields or derived from relations.

    Used for:
    - listing contributors on a project
    - returning the created membership row after POST
    """

    # Contributor.user is a FK -> expose selected user info in a flattened shape
    membership_id = serializers.IntegerField(source="id", read_only=True)

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    # Contributor.added_by is a FK -> expose who added the contributor
    added_by = serializers.CharField(source="added_by.username", read_only=True)

    class Meta:
        model = Contributor
        fields = (
            "membership_id",
            "user_id",
            "username",
            "email",
            "added_by",
        )
        # This serializer is output-only: no writes expected from client
        read_only_fields = fields


class ContributorWriteSerializer(serializers.Serializer):
    """
    Input-only serializer for adding a contributor to a project.

    The client sends lookup keys:
      - { "username": "..." } OR { "email": "..." }

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
        # Returns the first object matched by the QuerySet,
        # or None if no match exists
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

        Sensitive fields are server-controlled:
        - project comes from context (not payload)
        - added_by is request.user
        """
        request = self.context["request"]
        project: Project = self.context["project"]
        user = validated_data["resolved_user"]

        return Contributor.objects.create(
            project=project,
            user=user,
            added_by=request.user,
        )
