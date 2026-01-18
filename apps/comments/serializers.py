from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.issues.models import Issue
from .models import Comment


class CommentSummarySerializer(serializers.ModelSerializer):
    """Compact representation for embedding inside Issue responses."""
    author_id = serializers.IntegerField(source="author.id", read_only=True)
    author_username = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = Comment
        fields = ("uuid", "description", "author_id", "author_username", "created_at", "updated_at")
        read_only_fields = fields


class CommentSerializer(serializers.ModelSerializer):
    """
    Comment CRUD serializer.

    Rules:
    - author is forced from request.user
    - user must be contributor of issue.project (enforced again in view to return 403)
    """

    author = serializers.PrimaryKeyRelatedField(read_only=True)

    # keep global creation possible:
    issue = serializers.PrimaryKeyRelatedField(queryset=Issue.objects.all(), required=True)

    class Meta:
        model = Comment
        fields = ("uuid", "description", "issue", "author", "created_at", "updated_at")
        read_only_fields = ("uuid", "author", "created_at", "updated_at")

    def __init__(self, *args, **kwargs) -> None:
        """
        Browsable API dropdown: limit visible issues on GET/OPTIONS.
        Avoid blocking POST with 400 when user tries an issue they can't access;
        authorization should produce 403 from the view.
        """
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request is None or "issue" not in self.fields:
            return

        if not request.user.is_authenticated:
            self.fields["issue"].queryset = Issue.objects.none()
            return

        if request.method in ("GET", "HEAD", "OPTIONS"):
            user = request.user
            self.fields["issue"].queryset = (
                Issue.objects.filter(project__contributors=user)
                .distinct()
                .order_by("-updated_at")
            )

    def create(self, validated_data: dict[str, Any]) -> Comment:
        """Create/Add a comment"""
        request = self.context["request"]
        comment = Comment(author=request.user, **validated_data)

        try:
            comment.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return comment
