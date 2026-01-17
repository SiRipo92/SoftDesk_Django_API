from __future__ import annotations

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import Issue
from .permissions import IsIssueAuthor
from .serializers import (
    IssueAssigneeAddSerializer,
    IssueAssigneeReadSerializer,
    IssueSerializer,
)

User = get_user_model()


class IssueViewSet(viewsets.ModelViewSet):
    """
    Global issues endpoint.

    Visibility:
    - list/retrieve: issues for projects where user is contributor

    Write:
    - create: contributor of selected project
    - update/delete: issue author only
    - assignees add/remove: issue author only
    """

    serializer_class = IssueSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return issues visible to the current authenticated user."""
        user = self.request.user
        return (
            Issue.objects.select_related("project", "author")
            .prefetch_related("assignees")
            .filter(project__contributors=user)
            .distinct()
            .order_by("-updated_at")
        )

    def get_serializer_context(self):
        """
        Ensures /issues/{id}/assignees/ receives `issue` in serializer context,
        so the dropdown can be restricted to project contributors.
        """
        context = super().get_serializer_context()

        if self.action in ("assignees", "remove_assignee"):
            # get_object() uses get_queryset()
            context["issue"] = self.get_object()

        return context

    def get_serializer_class(self):
        """Make Browsable API show the correct form on /issues/{id}/assignees/"""
        if self.action in ("assignees", "remove_assignee"):
            return IssueAssigneeAddSerializer
        return IssueSerializer

    def get_permissions(self):
        # only author can modify/delete issue
        if self.action in ("update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), IsIssueAuthor()]

        # only author can add/remove assignees
        if (self.action in ("assignees", "remove_assignee")
                and self.request.method in ("POST", "DELETE")):
            return [permissions.IsAuthenticated(), IsIssueAuthor()]

        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        """Only project contributors can create an issue."""
        project = serializer.validated_data.get("project")
        user = self.request.user

        if project is None:
            raise PermissionDenied("Le projet est requis.")

        if not project.is_contributor(user):
            raise PermissionDenied("Vous devez être contributeur du projet.")

        serializer.save()

    @action(detail=True, methods=["get", "post"], url_path="assignees")
    def assignees(self, request, pk=None):
        """
        GET  /issues/{id}/assignees/ -> list assigned users
        POST /issues/{id}/assignees/ -> add one assignee
            (dropdown limited to contributors)
        """
        issue = self.get_object()

        if request.method == "GET":
            qs = issue.assignees.all().order_by("username")
            return Response(IssueAssigneeReadSerializer(qs, many=True).data)

        # get_serializer_context() already injects `issue`
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            IssueAssigneeReadSerializer(user).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["delete"], url_path=r"assignees/(?P<user_id>\d+)")
    def remove_assignee(self, request, user_id=None, pk=None):
        """
        DELETE /issues/{id}/assignees/{user_id}/
        Removes one assignee from the issue.
        Only the issue author can do this (enforced in get_permissions()).
        """
        issue = self.get_object()
        # Ensure the target user exists
        user = get_object_or_404(User, pk=int(user_id))

        # Ensure the user is actually assigned (otherwise return 404)
        if not issue.assignees.filter(pk=user.pk).exists():
            return Response(
                {"detail": "Cet utilisateur n'est pas assigné à cet issue."},
                status=status.HTTP_404_NOT_FOUND,
            )

        issue.assignees.remove(user)
        return Response(status=status.HTTP_204_NO_CONTENT)
