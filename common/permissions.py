from __future__ import annotations

from typing import Any

from django.apps import apps
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAuthorOrReadOnly(BasePermission):
    """
    Read-only for authenticated users (who already passed other permissions).
    Write allowed only to the object's author (or staff).
    """

    message = "Seul l'auteur de cette ressource peut la modifier ou la supprimer."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True

        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        if user.is_staff:
            return True

        return getattr(obj, "author", None) == user


class IsProjectAuthor(BasePermission):
    """
    Project owner permission (or staff).
    """

    message = "Seul l'auteur du projet peut effectuer cette action."

    def has_object_permission(self, request, view, obj) -> bool:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        if user.is_staff:
            return True

        return getattr(obj, "author", None) == user


class IsProjectContributor(BasePermission):
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
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        if user.is_staff:
            return True

        project = self._get_project_from_obj(obj)
        if project is None:
            return False

        # Author always has access (even if membership row is missing in DB)
        if getattr(project, "author_id", None) == user.id:
            return True

        return project.contributors.filter(pk=user.pk).exists()

    @staticmethod
    def _get_project_from_obj(obj) -> Any | None:
        if hasattr(obj, "contributors") and hasattr(obj, "author"):
            return obj

        if hasattr(obj, "project"):
            return getattr(obj, "project", None)

        issue = getattr(obj, "issue", None)
        if issue is not None:
            return getattr(issue, "project", None)

        return None


class IsProjectContributorFromRequestData(BasePermission):
    """
    Contributor check for CREATE actions where there is no object yet.
    Expects:
    - view.get_project() OR
    - URL kwarg: pk / project_id / project_pk
    """

    message = "Vous devez être contributeur à ce projet pour créer cette ressource."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False

        if user.is_staff:
            return True

        project = None

        if hasattr(view, "get_project"):
            project = view.get_project()

        if project is None:
            project_id = (
                view.kwargs.get("pk")
                or view.kwargs.get("project_id")
                or view.kwargs.get("project_pk")
            )
            if not project_id:
                return False

            ProjectModel = apps.get_model("projects", "Project")
            project = ProjectModel.objects.filter(pk=project_id).first()

        if project is None:
            return False

        if getattr(project, "author_id", None) == user.id:
            return True

        return project.contributors.filter(pk=user.pk).exists()


class IsAuthorOrStaff(BasePermission):
    """Allow access only to the object's author or staff users."""

    message = (
        "Seul l'auteur de cette ressource (ou un administrateur) "
        "peut effectuer cette action."
    )

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_staff or getattr(obj, "author_id", None) == user.id)
