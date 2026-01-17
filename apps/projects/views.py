"""
Projects app views.

Implements:
- CRUD for projects
- contributor management (add/list/remove) as custom actions
"""

from __future__ import annotations

from django.db.models import Count, Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.issues.models import Issue
from apps.issues.serializers import IssueSerializer
from common.permissions import IsProjectAuthor, IsProjectContributor

from .models import Contributor, Project
from .serializers import (
    ContributorCreateSerializer,
    ContributorReadSerializer,
    ProjectCreateSerializer,
    ProjectDetailSerializer,
    ProjectListSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    """Project CRUD + contributor management endpoints."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Return projects visible to the current user.

        Rules:
        - staff: can see all projects
        - non-staff: only projects where they are a contributor

        Important:
        - Use Exists() for filtering (non-staff) to avoid constraining joins.
          Otherwise, Count('memberships') can be affected by the filtering join.
        """
        user = self.request.user

        base_qs = Project.objects.all()

        if not user.is_staff:
            is_member = Contributor.objects.filter(
                project_id=OuterRef("pk"),
                user=user,
            )
            base_qs = base_qs.annotate(_is_member=Exists(is_member)).filter(
                _is_member=True
            )

        return base_qs.select_related("author").annotate(
            contributors_count=Count(
                "memberships",
                filter=~Q(memberships__user_id=F("author_id")),
                distinct=True,
            )
        )

    def get_serializer_context(self):
        """
        Inject project into serializer context for nested issues endpoints.

        This matters especially for the Browsable API POST form, because DRF
        uses get_serializer_context() when building the form.
        """
        context = super().get_serializer_context()

        if self.action in ("issues", "issue_detail"):
            context["project"] = self.get_object()

        return context

    def get_serializer_class(self):
        """
        Pick the serializer based on the endpoint.

        Why list vs detail?
        - List should stay light (contributors_count only).
        - Detail should show the contributor list.

        Why contributors action always returns ContributorCreateSerializer?
        - Browsable API builds the POST form from the serializer class of the GET
          request.
        """
        if self.action == "list":
            return ProjectListSerializer
        if self.action == "retrieve":
            return ProjectDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return ProjectCreateSerializer
        if self.action == "contributors":
            return ContributorCreateSerializer
        if self.action in ("issues", "issue_detail"):
            return IssueSerializer
        return ProjectDetailSerializer

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

        elif self.action == "issues":
            # GET/POST /projects/{id}/issues/ -> contributors can view/create issues
            perms = [permissions.IsAuthenticated, IsProjectContributor]

        else:
            perms = [permissions.IsAuthenticated]

        return [p() for p in perms]

    # ---------------------------
    # Contributor management
    # ---------------------------

    @action(detail=True, methods=["get", "post"], url_path="contributors")
    def contributors(
        self,
        request,
        pk=None,
    ):
        """
        GET  /projects/{id}/contributors/
            -> List membership rows (contributors + who added them)

        POST /projects/{id}/contributors/
            -> Add contributor using lookup keys:
               { "username": "..." } OR { "email": "..." }
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
        serializer = self.get_serializer(
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
    def remove_contributor(
        self,
        request,
        user_id=None,
        pk=None,
    ):
        """
        DELETE /projects/{id}/contributors/{user_id}/

        The regex (?P<user_id>\d+) means:
        - (?P<user_id> ...) captures a named group called "user_id"
        - \d+ means "one or more digits"
        DRF passes that value into the method argument: user_id=...
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

    @action(detail=True, methods=["get", "post"], url_path="issues")
    def issues(self, request, pk=None):
        """
        GET  /projects/{id}/issues/ -> list issues for this project
        POST /projects/{id}/issues/ -> create issue for this project

        Project is derived from URL, not selectable.
        Assignees are not set here (use /issues/{id}/assignees/).
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        if request.method == "GET":
            qs = (
                Issue.objects.filter(project=project)
                .select_related("project", "author")
                .prefetch_related("assignees")
                .order_by("-updated_at")
            )
            serializer = self.get_serializer(qs, many=True)
            return Response(serializer.data)

        data = request.data.copy()

        # If client sends a project, it must match URL (defensive safety)
        if "project" in data and str(data["project"]) != str(project.pk):
            return Response(
                {"project": "Le projet fourni ne correspond pas au projet de l'URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data.pop("project", None)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        issue = serializer.save(project=project)  # forces URL project

        return Response(self.get_serializer(issue).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["get", "patch", "delete"],
        url_path=r"issues/(?P<issue_id>\d+)",
    )
    def issue_detail(self, request, issue_id=None, pk=None):
        project = self.get_object()
        self.check_object_permissions(request, project)

        issue = get_object_or_404(Issue, pk=int(issue_id), project=project)

        if request.method == "GET":
            return Response(self.get_serializer(issue).data)

        # Only issue author can modify/delete (contributors can view)
        if issue.author_id != request.user.id:
            raise PermissionDenied(
                "Seul l'auteur de l'issue peut la modifier ou la supprimer."
            )

        if request.method == "DELETE":
            issue.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PATCH
        serializer = self.get_serializer(issue, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
