from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsCommentAuthor(BasePermission):
    """Allow write access only to the comment author."""

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and obj.author_id == user.id)
