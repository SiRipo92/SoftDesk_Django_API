"""
Projects app views.

Implements:
- CRUD for projects
- contributor management (add/list/remove) as custom actions
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsProjectAuthor, IsProjectContributor

from .models import Contributor, Project
from .serializers import (
    ContributorCreateSerializer,
    ContributorReadSerializer,
    ProjectSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    """Project CRUD + contributor management endpoints."""

    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Visibility rule:
        user can only see projects where they are a contributor.
        """
        user = self.request.user
        return (
            Project.objects.filter(contributors=user)
            .select_related("author")
            .distinct()
        )

    def get_permissions(self):
        """
        Permissions by action + HTTP method.

        """
        if self.action == "retrieve":
            perms = [permissions.IsAuthenticated, IsProjectContributor]

        elif self.action in ("update", "partial_update", "destroy"):
            perms = [permissions.IsAuthenticated, IsProjectAuthor]

        elif self.action == "contributors":
            # GET /projects/{id}/contributors/ -> any contributor can view
            if self.request.method == "GET":
                perms = [permissions.IsAuthenticated, IsProjectContributor]
            # POST /projects/{id}/contributors/ -> only project author can add
            else:
                perms = [permissions.IsAuthenticated, IsProjectAuthor]

        elif self.action == "remove_contributor":
            # DELETE /projects/{id}/contributors/{user_id}/ -> author only
            perms = [permissions.IsAuthenticated, IsProjectAuthor]

        else:
            perms = [permissions.IsAuthenticated]

        return [p() for p in perms]

    def perform_create(self, serializer):
        """
        After creating the project:
        ensure the author is also a contributor of their own project.
        """
        project = serializer.save()

        Contributor.objects.get_or_create(
            project=project,
            user=self.request.user,
            defaults={"added_by": self.request.user},
        )

    # ---------------------------
    # Contributor management
    # ---------------------------

    @action(detail=True, methods=["get", "post"], url_path="contributors")
    def contributors(self, request, pk=None):
        """
        GET  /projects/{id}/contributors/
        -> List membership rows for a project (who is a contributor + who added them).

        POST /projects/{id}/contributors/
        -> Add a contributor to the project
           Body: { "username": "..." } OR { "email": "..." }

        Why a single action?
        - DRF router can conflict when two separate @action methods
            share the same url_path.
        - A single action with methods=["get","post"] guarantees both HTTP
            methods are registered on the same endpoint.
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        # ---- GET: list contributors ----
        if request.method == "GET":
            qs = (
                Contributor.objects.filter(project=project)
                .select_related("user", "added_by")
                .order_by("created_at")
            )
            return Response(ContributorReadSerializer(qs, many=True).data)

        # ---- POST: add contributor ----
        serializer = ContributorCreateSerializer(
            data=request.data,
            context={"request": request, "project": project},
        )
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()

        return Response(
            ContributorReadSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"contributors/(?P<user_id>\d+)",
    )
    def remove_contributor(self, request, pk=None, user_id=None):
        """
        DELETE /projects/{id}/contributors/{user_id}/

        Removes a contributor membership row (owner-only).

        Notes:
        - user_id is the target contributor's user PK, not the Contributor row id.
        - This keeps the URL intuitive: you remove a user from a project.
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        # Defensive parsing (even though the URL regex is digits-only).
        try:
            target_user_id = int(user_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Identifiant utilisateur invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prevent the owner from removing themselves as contributor.
        # Otherwise they would lose visibility due to contributors-only queryset.
        if target_user_id == project.author_id:
            return Response(
                {"detail": "Impossible de retirer l'auteur du projet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership = get_object_or_404(
            Contributor,
            project=project,
            user_id=target_user_id,
        )
        membership.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
