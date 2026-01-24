from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsCommentAuthorOrStaff(BasePermission):
    """Allow write access to the comment author or staff users."""

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_staff or obj.author_id == user.id)
