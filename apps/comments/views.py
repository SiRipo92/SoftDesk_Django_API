from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import mixins, permissions, viewsets

from .models import Comment
from .permissions import IsCommentAuthorOrStaff
from .serializers import (
    CommentAdminListSerializer,
    CommentDetailSerializer,
    CommentWriteSerializer,
)


class CommentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Global comments endpoint (admin-oriented).

    Routes:
    - GET    /comments/          -> admin only, all comments newest->oldest
    - GET    /comments/{uuid}/   -> author or admin
    - PATCH  /comments/{uuid}/   -> author or admin
    - DELETE /comments/{uuid}/   -> author or admin

    Note:
    - We intentionally DO NOT expose POST here to avoid duplicating creation logic.
      Comment creation happens via: POST /issues/{issue_id}/comments/
    """

    lookup_field = "uuid"

    def get_queryset(self) -> QuerySet[Comment]:
        user = self.request.user

        qs = Comment.objects.select_related(
            "author", "issue", "issue__project"
        ).order_by("-created_at")

        if user.is_staff:
            return qs

        # Non-staff: only their own comments (defensive scoping)
        return qs.filter(author=user)

    def get_permissions(self):
        # Admin-only global listing
        if self.action == "list":
            return [permissions.IsAdminUser()]

        # Detail/write: author or admin
        if self.action in ("retrieve", "update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsCommentAuthorOrStaff()]

        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "list":
            return CommentAdminListSerializer

        if self.action == "retrieve":
            return CommentDetailSerializer

        if self.action in ("update", "partial_update"):
            return CommentWriteSerializer

        return CommentDetailSerializer
