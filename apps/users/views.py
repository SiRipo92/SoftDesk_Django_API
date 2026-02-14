"""
Users app views.

Endpoints:
- POST /users/        Public signup
- GET  /users/        Admin-only list
- GET  /users/{id}/   Self or admin
- PATCH/PUT /users/{id}/  Self or admin
- DELETE /users/{id}/     Self or admin

Notes:
- Related collections (projects, issues, comments) are exposed through their own
  resources and nested endpoints in their respective apps.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, QuerySet
from rest_framework import serializers, viewsets
from rest_framework.permissions import (
    AllowAny,
    BasePermission,
    IsAdminUser,
    IsAuthenticated,
)

from common.permissions import IsSelfOrAdmin

from .serializers import UserDetailSerializer, UserListSerializer, UserSerializer

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    """
    User CRUD with strict visibility rules.

    Access rules:
    - create: public (signup)
    - list: admin-only
    - retrieve/update/destroy: authenticated + (self or admin)
    """

    queryset = User.objects.all()

    def get_permissions(self) -> list[BasePermission]:
        if self.action == "create":
            return [AllowAny()]
        if self.action == "list":
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated(), IsSelfOrAdmin()]

    def get_serializer_class(self) -> type[serializers.Serializer]:
        """
        Select a serializer based on the current action.

        - list: admin overview serializer
        - retrieve: user detail serializer (profile + counters + previews)
        - create/update: base user serializer (write-capable)
        """
        if self.action == "list":
            return UserListSerializer
        if self.action == "retrieve":
            return UserDetailSerializer
        return UserSerializer

    def get_queryset(self) -> QuerySet[User]:
        """
        Return the queryset used by DRF to resolve User objects.

        DRF fetches the object from this queryset before running object permissions.
        If the target user is filtered out here, DRF returns 404 and IsSelfOrAdmin
        never runs. To return 403 for “exists but forbidden”, keep all users in the
        queryset for detail actions and enforce access via IsSelfOrAdmin.

        Annotations:
        - list: projects_count
        - detail: num_projects_owned, num_projects_added_as_contrib
        """
        if self.action == "list":
            # Admin-only list
            return (
                User.objects.all()
                .annotate(
                    projects_count=Count("contributed_projects"),
                )
                .order_by("id")
            )

            # Detail-like actions: do NOT filter to self, otherwise DRF returns 404
            # before IsSelfOrAdmin can produce a 403.
        return User.objects.all().annotate(
            num_projects_owned=Count("owned_projects"),
            num_projects_added_as_contrib=Count(
                "project_memberships",
                filter=~Q(project_memberships__project__author_id=F("id")),
            ),
        )
