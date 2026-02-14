"""
Issues app serializers.

Separates:
- Lightweight serializers for list views.
- Write serializers for create/update.
- Read-only detail serializer for retrieve.
- Sub-resource serializers for assignees.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers

from apps.comments.serializers import CommentSummarySerializer
from apps.users.models import User

from .models import Issue, IssueAssignee

# -------------------------------------------------------------------
# Shared constants
# -------------------------------------------------------------------

ISSUE_EDITABLE_FIELDS = (
    "title",
    "description",
    "priority",
    "tag",
    "status",
)

COMMENTS_PREVIEW_LIMIT = 10


# -------------------------------------------------------------------
# Assignees (nested resource under an Issue)
# -------------------------------------------------------------------


class IssueAssigneeReadSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a user assigned to an issue.

    Returned by:
    - GET /issues/{id}/assignees/
    - responses to POST /issues/{id}/assignees/
    """

    assignment_id = serializers.IntegerField(source="id", read_only=True)

    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    assigned_by_id = serializers.IntegerField(read_only=True, allow_null=True)
    assigned_by_username = serializers.SerializerMethodField()

    class Meta:
        model = IssueAssignee
        fields = (
            "assignment_id",
            "user_id",
            "username",
            "email",
            "assigned_at",
            "assigned_by_id",
            "assigned_by_username",
        )
        read_only_fields = fields

    def get_assigned_by_username(self, obj: IssueAssignee) -> str | None:
        """assigned_by is nullable (SET_NULL)."""
        return obj.assigned_by.username if obj.assigned_by else None


class IssueAssigneeAddSerializer(serializers.Serializer):
    """
    Add one assignee to an issue.

    Payload:
      {"user": <user_id>}

    Context:
    - context["issue"] must be provided by the view.
    - context["request"] must be provided by the view.
    """

    # Important:
    # Use ALL users here so "Invalid pk" truly means "user does not exist".
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    def validate_user(self, user: User) -> User:
        """
        Field-level validation.

        This runs AFTER the PK is resolved against User.objects.all().
        So if the user exists but is not a contributor, we can return
        a truthful business error instead of "Invalid pk".
        """
        issue: Issue = self.context["issue"]

        if not issue.project.is_contributor(user):
            raise serializers.ValidationError(
                "L'utilisateur doit être contributeur du projet."
            )

        return user

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        Cross-field validation (needs issue + user).

        Prevent duplicate assignments.
        """
        issue: Issue = self.context["issue"]
        user: User = attrs["user"]

        if IssueAssignee.objects.filter(issue=issue, user=user).exists():
            raise serializers.ValidationError(
                {"user": "Cet utilisateur est déjà assigné à cet issue."}
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> IssueAssignee:
        """Create assignment row with metadata."""
        request = self.context["request"]
        issue: Issue = self.context["issue"]
        user: User = validated_data["user"]

        try:
            return IssueAssignee.objects.create(
                issue=issue,
                user=user,
                assigned_by=request.user,
            )
        except IntegrityError as exc:
            # In case of race conditions, keep error consistent.
            raise serializers.ValidationError(
                {"user": "Cet utilisateur est déjà assigné à cet issue."}
            ) from exc


# -------------------------------------------------------------------
# Lightweight issue serializers (LIST / EMBED views)
# -------------------------------------------------------------------

# Centralize field sets so you can reason about payload contracts quickly.
ISSUE_GLOBAL_LIST_FIELDS = (
    "id",
    "title",
    "status",
    "project_id",
    "project_name",
    "author_id",
    "author_username",
    "assignees_count",
    "comments_count",
    "assigned_user_ids",
)

ISSUE_PROJECT_LIST_FIELDS = (
    "id",
    "title",
    "status",
    # If you consider author redundant in /projects/{id}/issues/,
    # keep it out (detail endpoint has it anyway).
    "assignees_count",
    "comments_count",
    "assigned_user_ids",
)

ISSUE_PROJECT_PREVIEW_FIELDS = (
    "id",
    "title",
    "assignees_count",
    "comments_count",
    "assigned_user_ids",
)


class AssignedUserIdsMixin(serializers.Serializer):
    """
    DRY helper: provide assigned_user_ids consistently across serializers.

    Important:
    DRF only collects declared fields from base classes that are also Serializers.
    A plain mixin class won't contribute fields to ModelSerializer.
    """

    assigned_user_ids = serializers.SerializerMethodField()

    def get_assigned_user_ids(self, obj: Issue) -> list[int]:
        """
        Return assigned user IDs from the join table (IssueAssignee).

        If assignee_links is prefetched, this uses the prefetch cache
        (no extra DB hits).
        """
        ids = {link.user_id for link in obj.assignee_links.all()}
        return sorted(ids)


class IssueListSerializer(AssignedUserIdsMixin, serializers.ModelSerializer):
    """
    Global list (/issues/).

    Contract:
    - compact list fields
    - no priority/tag (detail-only)
    - no updated_at (you don't want timestamps in list payloads)
    """

    project_id = serializers.IntegerField(source="project.id", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    assignees_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Issue
        fields = ISSUE_GLOBAL_LIST_FIELDS
        read_only_fields = fields


class IssuePreviewInProjectSerializer(
    AssignedUserIdsMixin, serializers.ModelSerializer
):
    """
    Embedded preview inside Project detail (/projects/{id}/).

    Contract:
    - only what is necessary to identify and “size” the issue
    - no status/priority/tag
    - no timestamps (updated_at removed)
    """

    assignees_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Issue
        fields = ISSUE_PROJECT_PREVIEW_FIELDS
        read_only_fields = fields


class IssueProjectListSerializer(AssignedUserIdsMixin, serializers.ModelSerializer):
    """
    Project-scoped list (/projects/{id}/issues/).

    Contract:
    - id + title + status for scanning the list
    - counts + assigned_user_ids for workload overview
    - no updated_at
    """

    assignees_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Issue
        fields = ISSUE_PROJECT_LIST_FIELDS
        read_only_fields = fields


# -------------------------------------------------------------------
# Write serializers (CREATE / UPDATE)
# -------------------------------------------------------------------


class IssueWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for nested create/update.

    Context for POST:
    - request (DRF)
    - project (required for nested creation)
    - author (optional override)
    """

    class Meta:
        model = Issue
        fields = ISSUE_EDITABLE_FIELDS

    def create(self, validated_data: dict[str, Any]) -> Issue:
        """Create Issue with server-controlled author/project injection."""
        request = self.context["request"]
        author = self.context.get("author") or request.user
        project = self.context.get("project")

        if project is None:
            raise serializers.ValidationError(
                {"project": "Ce serializer nécessite un projet en contexte."}
            )

        issue = Issue(author=author, project=project, **validated_data)

        try:
            issue.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return issue


# -------------------------------------------------------------------
# Issue detail serializer (RETRIEVE)
# -------------------------------------------------------------------


class IssueDetailSerializer(serializers.ModelSerializer):
    """
    Read-only Issue detail payload.

    Notes:
    - Full comments list is available via GET /issues/{id}/comments/ (paginated).
    - The detail payload includes a small comments_preview for convenience.
    """

    project_id = serializers.IntegerField(source="project.id", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    assignees = IssueAssigneeReadSerializer(
        source="assignee_links",
        many=True,
        read_only=True,
    )

    comments_count = serializers.SerializerMethodField()
    comments_preview = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = (
            "id",
            "title",
            "description",
            "priority",
            "tag",
            "status",
            "project_id",
            "project_name",
            "author_id",
            "author_username",
            "assignees",
            "comments_count",
            "comments_preview",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_comments_preview(self, obj: Issue) -> list[dict[str, Any]]:
        """Return the most recent comments with a limited payload."""
        qs = obj.comments.select_related("author").order_by("-created_at")[
            :COMMENTS_PREVIEW_LIMIT
        ]
        serializer = CommentSummarySerializer(qs, many=True, context=self.context)

        # DRF returns ReturnList[ReturnDict];
        # convert to plain dicts for typing.
        return [dict(item) for item in serializer.data]

    def get_comments_count(self, obj: Issue) -> int:
        """
        If the queryset annotated comments_count, use it.
        Otherwise, compute it with COUNT(*).
        """
        annotated = getattr(obj, "comments_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.comments.count()
