from __future__ import annotations

from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from apps.comments.models import Comment
from apps.comments.permissions import IsCommentAuthorOrStaff
from apps.comments.serializers import (
    CommentDetailSerializer,
    CommentSummarySerializer,
    CommentWriteSerializer,
)

from .models import Issue, IssueAssignee
from .permissions import IsIssueAuthor
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

    # ------------------------------------------------------------------
    # Queryset scope
    # ------------------------------------------------------------------

    def get_queryset(self):
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

        qs = Issue.objects.select_related("project", "author")

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

        if user.is_staff:
            return qs

        return qs.filter(project__contributors=user).distinct()

    # ------------------------------------------------------------------
    # Context + serializer selection
    # ------------------------------------------------------------------

    def get_serializer_context(self):
        """Inject issue into serializer context for nested sub-resources."""
        context = super().get_serializer_context()

        if self.action in (
            "assignees",
            "remove_assignee",
            "comments",
            "comment_detail",
        ):
            context["issue"] = self.get_object()

        return context

    def get_serializer_class(self):
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

    def get_permissions(self):
        """
        - update/partial_update/destroy: issue author / staff
        - assignees POST/DELETE: issue author
        - everything else: authenticated
        """
        if self.action in ("update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsIssueAuthor()]

        if self.action in ("assignees", "remove_assignee") and self.request.method in (
            "POST",
            "DELETE",
        ):
            return [permissions.IsAuthenticated(), IsIssueAuthor()]

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
    def assignees(self, request: Request, pk=None) -> Response:
        """
        GET  /issues/{id}/assignees/
        POST /issues/{id}/assignees/   body: {"user": <user_id>}
        """
        issue = self.get_object()

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
                type=int,
                location=OpenApiParameter.PATH,
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
    def remove_assignee(self, request: Request, user_id=None, pk=None) -> Response:
        """DELETE /issues/{id}/assignees/{user_id}/"""
        issue = self.get_object()

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
    def comments(self, request: Request, pk=None) -> Response:
        """
        GET  /issues/{issue_id}/comments/
        POST /issues/{issue_id}/comments/   body: {"description": "..."}
        """
        issue = self.get_object()

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

        if not (request.user.is_staff or issue.project.is_contributor(request.user)):
            raise PermissionDenied(
                "Vous devez être contributeur du projet pour commenter cet issue."
            )

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
                type=str,
                location=OpenApiParameter.PATH,
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
                type=str,
                location=OpenApiParameter.PATH,
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
                type=str,
                location=OpenApiParameter.PATH,
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
        pk=None,
    ) -> Response:
        """GET/PUT/PATCH/DELETE /issues/{issue_id}/comments/{uuid}/"""
        issue = self.get_object()

        comment = get_object_or_404(
            Comment.objects.select_related("author", "issue", "issue__project"),
            issue=issue,
            uuid=comment_uuid,
        )

        if request.method == "GET":
            serializer = self.get_serializer(comment)
            return Response(serializer.data, status=status.HTTP_200_OK)

        perm = IsCommentAuthorOrStaff()
        if not perm.has_object_permission(request, self, comment):
            raise PermissionDenied(
                "Modification interdite : auteur du commentaire ou administrateur "
                "uniquement."
            )

        if request.method == "DELETE":
            comment.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        is_partial = request.method == "PATCH"
        serializer = self.get_serializer(
            comment,
            data=request.data,
            partial=is_partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            CommentDetailSerializer(comment, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )
