from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied

from .models import Comment
from .permissions import IsCommentAuthor
from .serializers import CommentSerializer


class CommentViewSet(viewsets.ModelViewSet):
    """
    Global comments endpoint.

    - list: only comments created by the logged-in user
    - retrieve: only their own comments
    - create: only if user is contributor of issue.project
    - update/delete: only comment author
    """

    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "uuid"

    def get_queryset(self):
        user = self.request.user
        return (
            Comment.objects.select_related("issue", "issue__project", "author")
            .filter(author=user, issue__project__contributors=user)
            .order_by("-updated_at")
        )

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsCommentAuthor()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        issue = serializer.validated_data.get("issue")
        user = self.request.user

        if issue is None:
            raise PermissionDenied("L'issue est requis.")

        if not issue.project.is_contributor(user):
            raise PermissionDenied(
                "Vous devez être contributeur du projet pour commenter cet issue."
            )

        serializer.save()
