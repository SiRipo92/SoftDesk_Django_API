"""
Projects app views.

Implements:
- CRUD for projects
- Contributor management as nested actions
- Project-scoped issues list/create for nested context

Endpoints:
- /projects/                              (GET, POST)
- /projects/{id}/                         (GET, PATCH/PUT, DELETE)
- /projects/{id}/contributors/            (GET; POST)
- /projects/{id}/contributors/{user_id}/  (DELETE)
- /projects/{id}/issues/                  (GET; POST)
"""

from __future__ import annotations

from django.db.models import Count, Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from apps.issues.models import Issue
from apps.issues.serializers import (
    IssueDetailSerializer,
    IssueProjectListSerializer,
    IssueWriteSerializer,
)
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
    """
    Project CRUD + contributor management endpoints.

    Visibility:
    - staff: all projects
    - non-staff: only projects where a membership row exists
    """

    permission_classes = [permissions.IsAuthenticated]

    # ------------------------------------------------------------------
    # Queryset scope (visibility) + annotations (counts)
    # ------------------------------------------------------------------

    def get_queryset(self):
        """
        Return projects visible to the current user.

        Implementation detail:
        - Exists() avoids join-based filtering that can distort aggregates.
        """
        user = self.request.user
        base_qs = Project.objects.all()

        if not user.is_staff:
            is_member_qs = Contributor.objects.filter(
                project_id=OuterRef("pk"),
                user=user,
            )
            base_qs = base_qs.annotate(_is_member=Exists(is_member_qs)).filter(
                _is_member=True
            )

        return (
            base_qs.select_related("author")
            .annotate(
                contributors_count=Count(
                    "memberships",
                    filter=~Q(memberships__user_id=F("author_id")),
                    distinct=True,
                ),
                issues_count=Count("issues", distinct=True),
            )
            .order_by("-updated_at")
        )

    # ------------------------------------------------------------------
    # Serializer context (inject URL-derived objects for nested actions)
    # ------------------------------------------------------------------

    def get_serializer_context(self):
        """
        Add project to serializer context for nested actions.

        ContributorCreateSerializer expects:
        - project in context (server-derived, never trusted from payload)

        IssueWriteSerializer expects:
        - project in context for nested creation
        """
        context = super().get_serializer_context()

        if self.action in (
                "contributors",
                "remove_contributor",
                "issues",
                "issue_detail"
        ):
            context["project"] = self.get_object()

        return context

    # ------------------------------------------------------------------
    # Serializer selection (list vs detail vs input-only serializers)
    # ------------------------------------------------------------------

    def get_serializer_class(self):
        """
        Select serializer based on action and HTTP method.
        """
        if self.action == "list":
            return ProjectListSerializer

        if self.action == "retrieve":
            return ProjectDetailSerializer

        if self.action in ("create", "update", "partial_update"):
            return ProjectCreateSerializer

        if self.action == "contributors":
            if self.request.method == "GET":
                return ContributorReadSerializer
            return ContributorCreateSerializer

        if self.action == "issues":
            if self.request.method == "GET":
                return IssueProjectListSerializer
            return IssueWriteSerializer

        if self.action == "issue_detail":
            if self.request.method == "GET":
                return IssueDetailSerializer
            return IssueWriteSerializer

        return ProjectDetailSerializer

    # ------------------------------------------------------------------
    # Permission selection (action + method aware)
    # ------------------------------------------------------------------

    def get_permissions(self):
        """
        Permissions vary by action.

        - list/create: authenticated (queryset already scopes non-staff)
        - retrieve: contributors
        - update/partial_update/destroy: project author or staff
        - contributors:
            - GET: contributors
            - POST/DELETE: project author or staff
        - issues (list/create): contributors
        """
        if self.action in ("retrieve", "issues", "issue_detail"):
            perms = [permissions.IsAuthenticated, IsProjectContributor]

        elif self.action in ("update", "partial_update", "destroy"):
            perms = [permissions.IsAuthenticated, IsProjectAuthor]

        elif self.action == "contributors":
            if self.request.method == "GET":
                perms = [permissions.IsAuthenticated, IsProjectContributor]
            else:
                perms = [permissions.IsAuthenticated, IsProjectAuthor]

        elif self.action == "remove_contributor":
            perms = [permissions.IsAuthenticated, IsProjectAuthor]

        else:
            perms = [permissions.IsAuthenticated]

        return [p() for p in perms]

    # ------------------------------------------------------------------
    # Write responses: return read serializer for a stable API contract
    # ------------------------------------------------------------------

    def create(self, request: Request, *args, **kwargs) -> Response:
        """
        POST /projects/

        Returns ProjectDetailSerializer after creation to provide a complete
        resource representation in the response.
        """
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        project = write_serializer.save()

        read_serializer = ProjectDetailSerializer(
            project,
            context=self.get_serializer_context(),
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        """
        PUT/PATCH /projects/{id}/

        Returns ProjectDetailSerializer after update to provide a complete
        resource representation in the response.
        """
        partial = kwargs.pop("partial", False)
        project = self.get_object()

        write_serializer = self.get_serializer(
            project, data=request.data, partial=partial)
        write_serializer.is_valid(raise_exception=True)
        project = write_serializer.save()

        read_serializer = ProjectDetailSerializer(
            project,
            context=self.get_serializer_context(),
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    # ==================================================================
    # Contributor management
    # ==================================================================

    @extend_schema(
        methods=["GET"],
        summary="Lister les contributeurs d'un projet",
        description=(
                "Retourne les lignes d'adhésion (Contributor) du projet. "
                "L'auteur du projet peut être présent en base mais peut être "
                "masqué côté API selon la logique de sérialisation."
        ),
        responses=ContributorReadSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        summary="Ajouter un contributeur à un projet",
        description=(
                "Ajoute un contributeur via une clé de recherche : username OU email. "
                "Retourne la ligne d'adhésion créée."
        ),
        request=ContributorCreateSerializer,
        responses={201: ContributorReadSerializer},
    )
    @action(detail=True, methods=["get", "post"], url_path="contributors")
    def contributors(self, request: Request, pk=None) -> Response:
        """
        GET  /projects/{id}/contributors/
        POST /projects/{id}/contributors/
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        if request.method == "GET":
            qs = (
                Contributor.objects.filter(project=project)
                .exclude(user_id=project.author_id)
                .select_related("user", "added_by")
                .order_by("user__username")
            )

            page = self.paginate_queryset(qs)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer(qs, many=True)
            return Response(serializer.data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()

        return Response(
            ContributorReadSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Retirer un contributeur d'un projet",
        description=(
                "Supprime la ligne d'adhésion (Contributor) correspondant à user_id. "
                "L'auteur du projet ne peut pas être retiré."
        ),
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=int,
                location=OpenApiParameter.PATH,
                description="ID de l'utilisateur à retirer du projet.",
            ),
        ],
        responses={
            204: OpenApiResponse(description="Contributeur retiré."),
            400: OpenApiResponse(description="Requête invalide."),
            404: OpenApiResponse(description="Adhésion introuvable."),
        },
    )
    @action(detail=True, methods=["delete"], url_path=r"contributors/(?P<user_id>\d+)")
    def remove_contributor(self, request: Request, user_id=None, pk=None) -> Response:
        """
        DELETE /projects/{id}/contributors/{user_id}/
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        try:
            target_user_id = int(user_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Identifiant utilisateur invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

    # ==================================================================
    # Project-scoped issues endpoints
    # ==================================================================

    def get_issue_detail_queryset(self):
        """
        Queryset optimized for IssueDetailSerializer.

        - select_related: avoids extra queries for FK fields (project, author)
        - prefetch_related: avoids N+1 for assignee links and assigned_by
        - annotate: provides stable counts when serializers expect them
        """
        return (
            Issue.objects.select_related("project", "author")
            .prefetch_related(
                "assignee_links__user",
                "assignee_links__assigned_by",
            )
            .annotate(
                assignees_count=Count("assignee_links__user", distinct=True),
                comments_count=Count("comments", distinct=True),
            )
        )

    @extend_schema(
        methods=["GET"],
        summary="Lister les issues d'un projet",
        responses=IssueProjectListSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        summary="Créer une issue dans un projet",
        description="Le projet est dérivé de l'URL (non sélectionnable dans le body).",
        request=IssueWriteSerializer,
        responses={201: IssueDetailSerializer},
    )
    @action(detail=True, methods=["get", "post"], url_path="issues")
    def issues(self, request: Request, pk=None) -> Response:
        """
        GET  /projects/{id}/issues/
        POST /projects/{id}/issues/           body: {"title": "...", ...}

        Project is derived from the URL and is not writable in the payload.
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        if request.method == "GET":
            qs = (
                Issue.objects.filter(project=project)
                .select_related("project", "author")
                .prefetch_related("assignee_links")
                .annotate(
                    assignees_count=Count("assignee_links__user", distinct=True),
                    comments_count=Count("comments", distinct=True),
                )
                .order_by("-updated_at")
            )

            page = self.paginate_queryset(qs)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer(qs, many=True)
            return Response(serializer.data)

        data = request.data.copy()

        if "project" in data and str(data["project"]) != str(project.pk):
            return Response(
                {"project": "Le projet fourni ne correspond pas au projet de l'URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data.pop("project", None)

        serializer = IssueWriteSerializer(
            data=data,
            context={"request": request, "project": project},
        )
        serializer.is_valid(raise_exception=True)
        issue = serializer.save()

        return Response(
            IssueDetailSerializer(issue, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        methods=["GET"],
        summary="Détail d'une issue dans le contexte d'un projet",
        parameters=[
            OpenApiParameter(
                name="issue_id",
                type=int,
                location=OpenApiParameter.PATH,
                description="ID de l'issue.",
            ),
        ],
        responses={200: IssueDetailSerializer},
    )
    @extend_schema(
        methods=["PUT", "PATCH"],
        summary="Modifier une issue (auteur ou admin)",
        parameters=[
            OpenApiParameter(
                name="issue_id",
                type=int,
                location=OpenApiParameter.PATH,
                description="ID de l'issue.",
            ),
        ],
        request=IssueWriteSerializer,
        responses={200: IssueDetailSerializer},
    )
    @extend_schema(
        methods=["DELETE"],
        summary="Supprimer une issue (auteur ou admin)",
        parameters=[
            OpenApiParameter(
                name="issue_id",
                type=int,
                location=OpenApiParameter.PATH,
                description="ID de l'issue.",
            ),
        ],
        responses={204: OpenApiResponse(description="Issue supprimée.")},
    )
    @action(
        detail=True,
        methods=["get", "put", "patch", "delete"],
        url_path=r"issues/(?P<issue_id>\d+)",
    )
    def issue_detail(self, request: Request, issue_id=None, pk=None) -> Response:
        """
        /projects/{project_id}/issues/{issue_id}/

        - GET: contributors can view
        - PUT/PATCH/DELETE: staff OR issue author
        """
        project = self.get_object()
        self.check_object_permissions(request, project)

        try:
            target_issue_id = int(issue_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Identifiant d'issue invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issue = get_object_or_404(
            self.get_issue_detail_queryset(),
            pk=target_issue_id,
            project=project,
        )

        if request.method == "GET":
            serializer = self.get_serializer(issue)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # staff OR issue author only
        if not (request.user.is_staff or request.user.id == issue.author_id):
            raise PermissionDenied(
                "Seul l'auteur de l'issue (ou un admin) peut modifier/supprimer."
            )

        data = request.data.copy()
        data.pop("project", None)

        serializer = self.get_serializer(
            issue, data=data, partial=(request.method == "PATCH"))
        serializer.is_valid(raise_exception=True)
        issue = serializer.save()
        issue = self.get_issue_detail_queryset().get(pk=issue.pk)

        return Response(
            IssueDetailSerializer(issue, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )
