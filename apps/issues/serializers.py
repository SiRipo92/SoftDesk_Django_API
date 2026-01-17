from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.projects.models import Project

from .models import Issue

User = get_user_model()


class IssueAssigneeReadSerializer(serializers.ModelSerializer):
    """Read-only representation of a user assigned to an issue."""

    user_id = serializers.IntegerField(source="id", read_only=True)

    class Meta:
        model = User
        fields = ("user_id", "username", "email")
        read_only_fields = fields


class IssueAssigneeAddSerializer(serializers.Serializer):
    """
    Add ONE assignee to an issue.

    Browsable API behavior:
    - Shows a dropdown of allowed users (contributors of issue.project)
    """

    # Dropdown of allowed users (queryset is set in __init__)
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        issue: Issue | None = self.context.get("issue")
        if issue is not None:
            # This includes the project owner in the contributor/membership row.
            self.fields["user"].queryset = issue.project.contributors.all()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        issue: Issue = self.context["issue"]
        user: User = attrs["user"]

        # Defensive check: must still be contributor
        if not issue.project.is_contributor(user):
            raise serializers.ValidationError(
                "L'utilisateur doit être contributeur du projet."
            )

        # Prevent duplicates
        if issue.assignees.filter(pk=user.pk).exists():
            raise serializers.ValidationError(
                "Cet utilisateur est déjà assigné à cet issue."
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        issue: Issue = self.context["issue"]
        user: User = validated_data["user"]
        issue.assignees.add(user)
        return user


class IssueSummarySerializer(serializers.ModelSerializer):
    """Compact issue representation for embedding in project detail responses."""

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    assignees_count = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = (
            "id",
            "title",
            "status",
            "priority",
            "tag",
            "author_id",
            "assignees_count",
            "updated_at",
        )
        read_only_fields = fields

    def get_assignees_count(self, obj: Issue) -> int:
        """Return the number of assigned users."""
        return obj.assignees.count()


class IssueSerializer(serializers.ModelSerializer):
    """
    Issue CRUD serializer.

    Design choices (matching your rules):
    - project is chosen on global POST /issues/,
        but is implicit on POST /projects/{id}/issues/
    - assignees are read-only here
        (managed via /issues/{id}/assignees/ endpoints)
    """

    # For output (read): show assignees as user objects
    assignees = IssueAssigneeReadSerializer(many=True, read_only=True)

    # For global creation: project must still be writable
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(), required=False
    )

    class Meta:
        model = Issue
        fields = (
            "id",
            "title",
            "description",
            "priority",
            "tag",
            "status",
            "project",
            "author",
            "assignees",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "author", "created_at", "updated_at", "assignees")

    def __init__(self, *args, **kwargs) -> None:
        """
        Nested project context:
        - Hide 'project' from WRITE forms (POST/PUT/PATCH)
            so it's not selectable in Browsable API.
        - Keep 'project' in OUTPUT JSON when an instance exists.
        """
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        project = self.context.get("project")

        is_nested = request is not None and project is not None
        is_write = request is not None and request.method in ("POST", "PUT", "PATCH")
        is_input_serializer = self.instance is None  # no instance = form/input mode

        if is_nested and is_write and is_input_serializer:
            self.fields.pop("project", None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Ensure project is available either from context (nested endpoint)
        or from payload (global endpoint).
        """
        project = (
            self.context.get("project")
            or attrs.get("project")
            or getattr(self.instance, "project", None)
        )
        if project is None:
            raise serializers.ValidationError({"project": "Ce champ est requis."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Issue:
        """
        Create an Issue.

        - author is forced from request.user
        - project comes from:
            * context["project"] on nested endpoints
            * validated_data["project"] on global endpoint
        """
        request = self.context["request"]
        project = self.context.get("project") or validated_data.get("project")

        issue = Issue(
            author=request.user,
            project=project,
            title=validated_data.get("title"),
            description=validated_data.get("description", ""),
            priority=validated_data.get("priority", ""),
            tag=validated_data.get("tag", ""),
            status=validated_data.get(
                "status", Issue._meta.get_field("status").default
            ),
        )

        try:
            issue.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return issue

    def update(self, instance: Issue, validated_data: dict[str, Any]) -> Issue:
        """
        Update an Issue.

        - project cannot be changed
        - assignees are not handled here (separate endpoints)
        """
        if (
            "project" in validated_data
            and validated_data["project"] != instance.project
        ):
            raise serializers.ValidationError(
                {"project": "Impossible de changer le projet d'un issue existant."}
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        try:
            instance.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return instance
