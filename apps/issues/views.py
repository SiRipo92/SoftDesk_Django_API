from __future__ import annotations

from typing import Any

from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.comments.models import Comment
from apps.comments.serializers import (
    CommentDetailSerializer,
    CommentSummarySerializer,
    CommentWriteSerializer,
)

from .models import Issue, IssueAssignee
from common.permissions import IsCommentAuthorOrStaff, IsIssueAuthor, IsProjectContributor
from .serializers import (
    IssueAssigneeAddSerializer,
    IssueAssigneeReadSerializer,
    IssueDetailSerializer,
    IssueListSerializer,
    IssueWriteSerializer,
)


class IssueViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Canonical issue resource.

    Routes:
    - /issues/                              (GET)
    - /issues/{id}/                         (GET, PATCH/PUT, DELETE)
    - /issues/{id}/assignees/               (GET, POST)
    - /issues/{id}/assignees/{user_id}/     (DELETE)
    - /issues/{id}/comments/                (GET, POST)
    - /issues/{id}/comments/{uuid}/         (GET, PATCH/PUT, DELETE)
    """

    permission_classes = [permissions.IsAuthenticated]

    # Provide a base queryset so drf-spectacular can always resolve the model.
    # Using `.none()` avoids any accidental DB hit at import time while keeping
    # model metadata.
    queryset = Issue.objects.none()

    def __init__(self, **kwargs: Any) -> None:
        """
        Initialize per-request cache attributes.

        Some linters warn if instance attributes are created outside __init__.
        DRF instantiates view classes per request, so caching here is safe.
        """
        super().__init__(**kwargs)
        self._cached_issue: Issue | None = None

    def _get_cached_issue(self) -> Issue:
        """
        Return the Issue for detail routes, cached for the lifetime of the request.

        get_object() already performs object-level permission checks via
        check_object_permissions(request, obj).
        """
        if self._cached_issue is None:
            self._cached_issue = self.get_object()
        return self._cached_issue

    # ------------------------------------------------------------------
    # Queryset scope
    # ------------------------------------------------------------------

    def get_queryset(self) -> QuerySet[Issue]:
        """
        Return issues visible to the current authenticated user.

        - staff: all issues
        - non-staff: issues in projects where user is a contributor
        """
        # drf-spectacular sets this flag during schema generation.
        # Return a lightweight queryset with the correct model
        # so it can infer path param types.
        if getattr(self, "swagger_fake_view", False):
            return Issue.objects.all()

        user = self.request.user

        qs: QuerySet[Issue] = Issue.objects.select_related("project", "author")

        # Only fetch heavy relations when needed
        if self.action in ("retrieve", "assignees", "remove_assignee"):
            qs = qs.prefetch_related(
                "assignee_links__user",
                "assignee_links__assigned_by",
            )
        else:
            qs = qs.prefetch_related("assignee_links")

        qs = qs.annotate(
            assignees_count=Count("assignee_links__user", distinct=True),
            comments_count=Count("comments", distinct=True),
        ).order_by("-updated_at")

        if getattr(user, "is_staff", False):
            return qs

        # Non-staff: restrict issues to projects where user is a contributor.
        # This also prevents non-members from probing issue IDs (returns 404).
        return qs.filter(project__contributors=user).distinct()

    # ------------------------------------------------------------------
    # Context + serializer selection
    # ------------------------------------------------------------------

    def get_serializer_context(self) -> dict[str, Any]:
        """
        Inject issue into serializer context for nested sub-resources.

        CommentWriteSerializer.create() expects:
        - request in context (provided by DRF)
        - issue in context (derived from URL, not trusted from payload)
        """
        context = super().get_serializer_context()

        if self.action in (
                "assignees",
                "remove_assignee",
                "comments",
                "comment_detail"
        ):
            context["issue"] = self._get_cached_issue()

        return context

    def get_serializer_class(self) -> type[BaseSerializer]:
        """Select serializers per action and method."""
        if self.action == "list":
            return IssueListSerializer

        if self.action == "retrieve":
            return IssueDetailSerializer

        if self.action in ("update", "partial_update"):
            return IssueWriteSerializer

        if self.action == "assignees":
            if self.request.method == "GET":
                return IssueAssigneeReadSerializer
            return IssueAssigneeAddSerializer

        if self.action == "comments":
            return (
                CommentWriteSerializer
                if self.request.method == "POST"
                else CommentSummarySerializer
            )

        if self.action == "comment_detail":
            if self.request.method in ("PUT", "PATCH"):
                return CommentWriteSerializer
            return CommentDetailSerializer

        return IssueDetailSerializer

    def get_permissions(self) -> list[BasePermission]:
        """
        - update/partial_update/destroy: issue author / staff
        - assignees POST/DELETE: issue author / staff
        - comments POST: project contributor / staff
        - comment_detail PUT/PATCH/DELETE: comment author / staff (checked manually)
        - everything else: authenticated
        """
        if self.action in ("update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsIssueAuthor()]

        if self.action in ("assignees", "remove_assignee") and self.request.method in ("POST", "DELETE"):
            return [permissions.IsAuthenticated(), IsIssueAuthor()]

        if self.action == "comments" and self.request.method == "POST":
            # This will be evaluated against the Issue object (via get_object()).
            return [permissions.IsAuthenticated(), IsProjectContributor()]

        return [permissions.IsAuthenticated()]

    # ------------------------------------------------------------------
    # Assignees management
    # ------------------------------------------------------------------

    @extend_schema(
        methods=["GET"],
        summary="Lister les assignés d'une issue",
        responses=IssueAssigneeReadSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        summary="Assigner un utilisateur à une issue",
        description=(
            "Le body attend un champ 'user' (id). "
            "L'utilisateur doit être contributeur du projet."
        ),
        request=IssueAssigneeAddSerializer,
        responses={201: IssueAssigneeReadSerializer},
    )
    @action(detail=True, methods=["get", "post"], url_path="assignees")
    def assignees(self, request: Request, pk: str | None = None) -> Response:
        """
        GET  /issues/{id}/assignees/
        POST /issues/{id}/assignees/   body: {"user": <user_id>}
        """
        _ = pk  # required by DRF router for detail routes

        issue = self._get_cached_issue()

        if request.method == "GET":
            qs = issue.assignee_links.select_related("user", "assigned_by").order_by(
                "user__username"
            )
            page = self.paginate_queryset(qs)
            if page is not None:
                serializer = IssueAssigneeReadSerializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            return Response(IssueAssigneeReadSerializer(qs, many=True).data)

        serializer = IssueAssigneeAddSerializer(
            data=request.data,
            context={"request": request, "issue": issue},
        )
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save()

        return Response(
            IssueAssigneeReadSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Retirer un assigné d'une issue",
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.INT,
                location="path",
                description="ID de l'utilisateur à désassigner.",
            ),
        ],
        responses={
            204: OpenApiResponse(description="Assignation supprimée."),
            400: OpenApiResponse(description="Identifiant utilisateur invalide."),
            404: OpenApiResponse(description="Assignation introuvable."),
        },
    )
    @action(detail=True, methods=["delete"], url_path=r"assignees/(?P<user_id>\d+)")
    def remove_assignee(
            self,
            request: Request,
            user_id: str | None = None,
            pk: str | None = None,
    ) -> Response:
        """DELETE /issues/{id}/assignees/{user_id}/"""
        _unused_pk: str | None = pk
        _unused_request: Request = request

        issue = self._get_cached_issue()

        try:
            user_id_int = int(user_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Identifiant utilisateur invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment = get_object_or_404(
            IssueAssignee.objects.select_related("user"),
            issue=issue,
            user_id=user_id_int,
        )
        assignment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # Comments management
    # ------------------------------------------------------------------

    @extend_schema(
        methods=["GET"],
        summary="Lister les commentaires d'une issue",
        responses=CommentSummarySerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        summary="Ajouter un commentaire à une issue",
        request=CommentWriteSerializer,
        responses={201: CommentDetailSerializer},
    )
    @action(detail=True, methods=["get", "post"], url_path="comments")
    def comments(self, request: Request, pk: str | None = None) -> Response:
        """
        GET  /issues/{issue_id}/comments/
        POST /issues/{issue_id}/comments/   body: {"description": "..."}
        """
        _ = pk

        issue = self._get_cached_issue()

        if request.method == "GET":
            qs = (
                Comment.objects.filter(issue=issue)
                .select_related("author")
                .order_by("-created_at")
            )
            page = self.paginate_queryset(qs)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer(qs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # get_object() already enforced object permissions.
        # For POST on this action, get_permissions() includes IsProjectContributor,
        # so non-contributors will be blocked before reaching serializer.save().

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save()

        return Response(
            CommentDetailSerializer(comment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        methods=["GET"],
        summary="Détail d'un commentaire",
        parameters=[
            OpenApiParameter(
                name="comment_uuid",
                type=OpenApiTypes.UUID,
                location="path",
                description="UUID du commentaire.",
            ),
        ],
        responses={200: CommentDetailSerializer},
    )
    @extend_schema(
        methods=["PUT", "PATCH"],
        summary="Modifier un commentaire (auteur ou admin)",
        parameters=[
            OpenApiParameter(
                name="comment_uuid",
                type=OpenApiTypes.UUID,
                location="path",
                description="UUID du commentaire.",
            ),
        ],
        request=CommentWriteSerializer,
        responses={200: CommentDetailSerializer},
    )
    @extend_schema(
        methods=["DELETE"],
        summary="Supprimer un commentaire (auteur ou admin)",
        parameters=[
            OpenApiParameter(
                name="comment_uuid",
                type=OpenApiTypes.UUID,
                location="path",
                description="UUID du commentaire.",
            ),
        ],
        responses={204: OpenApiResponse(description="Commentaire supprimé.")},
    )
    @action(
        detail=True,
        methods=["get", "put", "patch", "delete"],
        url_path=r"comments/(?P<comment_uuid>[0-9a-fA-F-]{36})",
    )
    def comment_detail(
            self,
            request: Request,
            comment_uuid: str | None = None,
            pk: str | None = None,
    ) -> Response:
        """GET/PUT/PATCH/DELETE /issues/{issue_id}/comments/{uuid}/"""
        _ = pk

        issue = self.get_object()
        self._cached_issue = issue

        comment = get_object_or_404(
            Comment.objects.select_related("author", "issue", "issue__project"),
            issue=issue,
            uuid=comment_uuid,
        )

        if request.method == "GET":
            serializer = self.get_serializer(comment)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Manual object-level permission gate for write operations.
        comment_perm = IsCommentAuthorOrStaff()
        if not comment_perm.has_object_permission(request, self, comment):
            raise PermissionDenied(comment_perm.message)

        if request.method == "DELETE":
            comment.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.get_serializer(
            comment,
            data=request.data,
            partial=(request.method == "PATCH"),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            CommentDetailSerializer(comment, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )
