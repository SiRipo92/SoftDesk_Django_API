"""
Common DRF permissions shared across apps.

SoftDesk rules (from specs):
- Auth required for everything.
- Only project contributors may access a project and its related resources.
- Only the author of a resource may update/delete it (others read-only).
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAuthorOrReadOnly(BasePermission):
    """
    Allow read-only access to everyone (who already passed other permissions),
    but only allow write operations to the object's author.

    Expected: the object has an `author` attribute (FK to User).
    """

    message = "Seul l'auteur de cette ressource peut la modifier ou la supprimer."

    def has_object_permission(self, request, view, obj) -> bool:
        # Read-only methods are allowed (GET/HEAD/OPTIONS)
        if request.method in SAFE_METHODS:
            return True

        # Write methods require obj.author == request.user
        author = getattr(obj, "author", None)
        return author == request.user


class IsProjectAuthor(BasePermission):
    """
    Only allow the project's author (owner) to perform the action.

    Useful for:
    - adding/removing contributors
    - project-level admin actions
    """

    message = "Seul l'auteur du projet peut effectuer cette action."

    def has_object_permission(self, request, view, obj) -> bool:
        # `obj` is expected to be a Project
        return getattr(obj, "author", None) == request.user


class IsProjectContributor(BasePermission):
    """
    Allow access only if the authenticated user is a contributor of the project.
    - object-level (GET/PATCH/DELETE on an existing project/issue/comment)

    Works for:
    - Project object permissions
    - Issue/Comment object permissions (must reach the related project)

    Expected object shapes:
    - Project: obj has contributors or memberships
    - Issue: obj.project exists
    - Comment: obj.issue.project exists
    """

    message = "Vous devez être contributeur à ce projet pour accéder à cette ressource."

    def has_object_permission(self, request, view, obj) -> bool:
        project = self._get_project_from_obj(obj)
        if project is None:
            # If we can't resolve a project from the object, deny by default
            return False

        # Project model has a ManyToMany "contributors" through Contributor
        return project.contributors.filter(pk=request.user.pk).exists()

    @staticmethod
    def _get_project_from_obj(obj) -> Any | None:
        """
        Resolve the Project from various resource types.

        - Project -> Project
        - Issue -> issue.project
        - Comment -> comment.issue.project
        """
        # Project itself
        if hasattr(obj, "contributors") and hasattr(obj, "author"):
            return obj

        # Issue
        if hasattr(obj, "project"):
            return getattr(obj, "project", None)

        # Comment
        issue = getattr(obj, "issue", None)
        if issue is not None:
            return getattr(issue, "project", None)

        return None


class IsProjectContributorFromRequestData(BasePermission):
    """
    Contributor check for CREATE actions, where there is no object yet.
    - request-level (POST create when no object exists yet)

    Example use:
    - POST /projects/{project_id}/issues/
    - POST /projects/{project_id}/issues/{issue_id}/comments/

    This permission expects the view to provide a `get_project()` method
    OR a `project_id` / `project_pk` kwarg.
    """

    message = "Vous devez être contributeur à ce projet pour créer cette ressource."

    def has_permission(self, request, view) -> bool:
        project = None

        # Helper for the view
        if hasattr(view, "get_project"):
            project = view.get_project()

        # Fallback to URL kwargs
        if project is None:
            project_id = view.kwargs.get("project_id") or view.kwargs.get("project_pk")
            if not project_id:
                return False
            project = view.get_queryset().model.objects.filter(pk=project_id).first()

        if project is None:
            return False

        return project.contributors.filter(pk=request.user.pk).exists()
