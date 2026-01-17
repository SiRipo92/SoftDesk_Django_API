# apps/issues/permissions.py
from rest_framework.permissions import BasePermission

from .models import Issue


class IsIssueAuthor(BasePermission):
    """Allow access only to the Issue author."""

    message = "Seul l'auteur de l'issue peut effectuer cette action."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Normal case: obj is an Issue
        author_id = getattr(obj, "author_id", None)
        if author_id is not None:
            return author_id == user.id

        # Fallback case: obj is NOT an Issue (e.g. User)
        issue_pk = view.kwargs.get("pk") or view.kwargs.get("issue_id")
        if not issue_pk:
            return False

        return Issue.objects.filter(pk=issue_pk, author_id=user.id).exists()
