from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Comment

User = get_user_model()


# ------------------------------------------------------------------
# Summarized (nested) comment views inside Issue
# ------------------------------------------------------------------


class CommentSummarySerializer(serializers.ModelSerializer):
    """
    Small, stable representation used for:
    - embedded comments inside IssueDetailSerializer
    - issue-scoped comment list (/issues/{id}/comments/)
    """

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "uuid",
            "description",
            "author_id",
            "author_username",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


# ------------------------------------------------------------------
# READ view for comment details
# ------------------------------------------------------------------


class CommentDetailSerializer(serializers.ModelSerializer):
    """
    Full read-only comment payload (detail endpoint).
    Includes extra context so the payload is self-explanatory.
    """

    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)
    author_email = serializers.EmailField(source="author.email", read_only=True)

    issue_id = serializers.IntegerField(source="issue.id", read_only=True)
    issue_title = serializers.CharField(source="issue.title", read_only=True)
    project_id = serializers.IntegerField(source="issue.project.id", read_only=True)
    project_name = serializers.CharField(source="issue.project.name", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "uuid",
            "description",
            "issue_id",
            "issue_title",
            "project_id",
            "project_name",
            "author_id",
            "author_username",
            "author_email",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


# ------------------------------------------------------------------
# Write view for posting/editing/deleting comments
# ------------------------------------------------------------------


class CommentWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for comment create/update.

    Rules:
    - `issue` is not writable here (nested route controls it).
    - `issue` must be provided via serializer context.
    - `author` is always request.user.
    """

    class Meta:
        model = Comment
        fields = ("description",)

    def create(self, validated_data: dict[str, Any]) -> Comment:
        request = self.context["request"]
        issue = self.context.get("issue")

        if request is None:
            raise serializers.ValidationError(
                {"request": "Requête manquante en contexte."}
            )

        if issue is None:
            raise serializers.ValidationError(
                {"issue": "Issue manquante en contexte."}
            )

        comment = Comment(issue=issue, author=request.user, **validated_data)

        try:
            comment.save()
        except DjangoValidationError as exc:
            # Converts Django model validation errors
            # into DRF validation errors
            raise serializers.ValidationError(exc.message_dict) from exc

        return comment


# ------------------------------------------------------------------
# READ view for listing for overall comments
# ------------------------------------------------------------------


class CommentListSerializer(serializers.ModelSerializer):
    """
    List representation for /comments/.

    Keeps payload smaller than full detail while still giving enough context
    to audit comments globally.
    """

    issue_id = serializers.IntegerField(source="issue.id", read_only=True)
    project_id = serializers.IntegerField(source="issue.project.id", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "uuid",
            "project_id",
            "issue_id",
        )
        read_only_fields = fields
