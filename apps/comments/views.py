"""
Comments app views.

Implements:
- Global comment endpoints (list/retrieve/update/delete)

Routes:
- GET    /comments/         -> authenticated (staff sees all; non-staff sees own)
- GET    /comments/{uuid}/  -> author or staff
- PATCH  /comments/{uuid}/  -> author or staff
- DELETE /comments/{uuid}/  -> author or staff

Note:
- We intentionally DO NOT expose POST here to avoid duplicating creation logic.
  Comment creation happens via: POST /issues/{issue_id}/comments/
"""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import mixins, permissions, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.serializers import BaseSerializer

from common.permissions import IsCommentAuthorOrStaff
from .models import Comment
from .serializers import (
    CommentListSerializer,
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
    Comment endpoints.

    This viewset provides a global entry point for comments, with visibility
    scoped by the authenticated user unless the user is staff.

    Security model:
    - list: authenticated users can list comments (staff sees all; non-staff sees own)
    - retrieve/update/destroy: authenticated + (author or staff)
    """

    lookup_field = "uuid"

    # Base queryset for schema generation / model inference (drf-spectacular).
    queryset = Comment.objects.none()

    def get_queryset(self) -> QuerySet[Comment]:
        """
        Return comments visible to the current user.

        Rules:
        - swagger_fake_view: return lightweight queryset for schema generation.
        - staff: all comments (global audit use-case)
        - non-staff: only comments authored by the user
        """

        if getattr(self, "swagger_fake_view", False):
            return Comment.objects.all()

        user = self.request.user

        qs: QuerySet[Comment] = (
            Comment.objects.select_related("author", "issue", "issue__project")
            .order_by("-created_at")
        )

        if getattr(user, "is_staff", False):
            return qs

        return qs.filter(author=user)

    def get_permissions(self) -> list[BasePermission]:
        """
        Return permission instances based on the current action.

        - list: authenticated
        - retrieve/update/partial_update/destroy: authenticated + author-or-staff
        - fallback: authenticated
        """
        # Authenticated users can list their own comments
        if self.action == "list":
            return [permissions.IsAuthenticated()]

        # Only author or staff can retrieve/update/delete a specific comment
        if self.action in ("retrieve", "update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsCommentAuthorOrStaff()]

        return [permissions.IsAuthenticated()]

    def get_serializer_class(self) -> type[BaseSerializer]:
        """
        Select the serializer class based on action.

        - list: lightweight list payload
        - retrieve: full detail payload
        - update/partial_update: write serializer (input payload)
        - fallback: detail serializer
        """
        if self.action == "list":
            return CommentListSerializer

        if self.action == "retrieve":
            return CommentDetailSerializer

        if self.action in ("update", "partial_update"):
            return CommentWriteSerializer

        return CommentDetailSerializer
