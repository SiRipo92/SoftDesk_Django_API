from __future__ import annotations

from typing import Any

from django.apps import apps
from rest_framework.permissions import SAFE_METHODS, BasePermission

# ------------------------------------------------------------------
# Shared helpers / base classes
# ------------------------------------------------------------------


class AuthenticatedPermission(BasePermission):
    """
    Base permission that requires an authenticated user.

    Use this when you want the permission itself
    to enforce authentication, instead of relying on the view's
    permission_classes to include IsAuthenticated.
    """

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and getattr(user, "is_authenticated", False))

    @staticmethod
    def _user(request):
        """Return request.user safely (works with RequestFactory too)."""
        return getattr(request, "user", None)

    @staticmethod
    def _is_staff(user) -> bool:
        """Return True if user exists and is staff."""
        return bool(user and getattr(user, "is_staff", False))


class StaffOrOwnerPermission(AuthenticatedPermission):
    """
    Base permission for "staff OR owner".

    Subclasses must implement get_owner_id(obj)
    to return the owning user's id.
    """

    message = "Accès interdit."

    def get_owner_id(self, obj) -> int | None:
        """
        Return the owner user's id for the object, or None
        if not resolvable.
        """
        raise NotImplementedError

    def has_object_permission(self, request, view, obj) -> bool:
        user = self._user(request)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        if self._is_staff(user):
            return True

        owner_id = self.get_owner_id(obj)
        return owner_id is not None and owner_id == user.id


class StaffOrAuthorPermission(StaffOrOwnerPermission):
    """
    Specialization of StaffOrOwnerPermission for objects
    with an `author` FK.
    Uses `author_id` when available (no extra fetch),
    otherwise falls back to `author.id`.
    """

    def get_owner_id(self, obj) -> int | None:
        author_id = getattr(obj, "author_id", None)
        if author_id is not None:
            return int(author_id)

        author = getattr(obj, "author", None)
        return getattr(author, "id", None)


class ProjectResolverMixin:
    """
    Mixin to resolve a Project instance from different
    objects / contexts.

    Supported object shapes:
    - Project: obj has contributors + author
    - Issue: obj.project exists
    - Comment: obj.issue.project exists
    """

    @staticmethod
    def _get_project_from_obj(obj) -> Any | None:
        # Project
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

    @staticmethod
    def _get_project_id_from_view(view) -> str | None:
        """
        Extract project id from common kwarg names used in nested routers.
        """
        return (
            view.kwargs.get("pk")
            or view.kwargs.get("project_id")
            or view.kwargs.get("project_pk")
        )

    @staticmethod
    def _load_project_by_id(project_id: str):
        """
        Load Project model without importing apps.projects directly.
        """
        ProjectModel = apps.get_model("projects", "Project")
        return ProjectModel.objects.filter(pk=project_id).first()


# ------------------------------------------------------------------
# User-scoped permissions
# ------------------------------------------------------------------


class IsSelfOrAdmin(StaffOrOwnerPermission):
    """
    Allow object access only to:
    - staff users
    - the user whose profile is being accessed (self)

    Use for /users/{id}/ endpoints.
    """

    message = (
        "Accès interdit : vous ne pouvez accéder qu'à "
        "votre propre profil (sauf administrateur)."
    )

    def get_owner_id(self, obj) -> int | None:
        return getattr(obj, "pk", None)


# ------------------------------------------------------------------
# Generic "author" permissions
# ------------------------------------------------------------------


class IsAuthorOrStaff(StaffOrAuthorPermission):
    """
    Allow object access only to:
    - staff users
    - the object's author

    Expected: object has `author_id` (preferred) or `author`.
    """

    message = (
        "Seul l'auteur de cette ressource (ou un administrateur) "
        "peut effectuer cette action."
    )


class IsAuthorOrReadOnly(IsAuthorOrStaff):
    """
    Read-only for authenticated users (who already passed other permissions).
    Write allowed only to author (or staff).

    Note: this permission assumes authentication is already enforced
    (directly via AuthenticatedPermission base, or via view permissions).
    """

    message = "Seul l'auteur de cette ressource peut la modifier ou la supprimer."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return super().has_object_permission(request, view, obj)


# ------------------------------------------------------------------
# Project-scoped permissions
# ------------------------------------------------------------------


class IsProjectAuthor(IsAuthorOrStaff):
    """
    Project owner permission (or staff).

    Works because Project has author_id / author.
    """

    message = (
        "Seul l'auteur du projet (ou un administrateur) peut effectuer cette action."
    )


class IsProjectContributor(AuthenticatedPermission, ProjectResolverMixin):
    """
    Allow access if user is:
    - staff
    - project author
    - project contributor

    Supports objects:
    - Project
    - Issue (obj.project)
    - Comment (obj.issue.project)
    """

    message = "Vous devez être contributeur à ce projet pour accéder à cette ressource."

    def has_object_permission(self, request, view, obj) -> bool:
        user = self._user(request)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        if self._is_staff(user):
            return True

        project = self._get_project_from_obj(obj)
        if project is None:
            return False

        # Author always has access (even if membership row is missing)
        if getattr(project, "author_id", None) == user.id:
            return True

        return project.contributors.filter(pk=user.pk).exists()


# ------------------------------------------------------------------
# Issue-scoped permissions
# ------------------------------------------------------------------


class IsIssueAuthor(IsAuthorOrReadOnly):
    """
    Allow write operations only for the Issue author (or staff).

    Inherits the write gate behavior from IsAuthorOrReadOnly.
    """

    message = (
        "Seul l'auteur de l'issue (ou un administrateur) peut effectuer cette action."
    )


# ------------------------------------------------------------------
# Comment-scoped permissions
# ------------------------------------------------------------------


class IsCommentAuthorOrStaff(IsAuthorOrStaff):
    """
    Allow access only to the comment author or staff users.

    This is functionally identical to IsAuthorOrStaff
    but keeps a comment-specific message for clearer API errors
    and easier soutenance explanation.
    """

    message = (
        "Seul l'auteur du commentaire (ou un administrateur) "
        "peut accéder à cette ressource."
    )
