from django.contrib.auth import get_user_model
from django.db.models import Count, F, Prefetch, Q
from rest_framework import permissions, viewsets

from apps.projects.models import Project

from .permissions import IsSelfOrAdmin
from .serializers import UserDetailSerializer, UserListSerializer, UserSerializer

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()

    def get_permissions(self):
        """Validates user permissions"""
        if self.action == "create":
            return [permissions.AllowAny()]
        if self.action == "list":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated(), IsSelfOrAdmin()]

    def get_serializer_class(self):
        """
        Select serializer based on action:

        - create/update: UserSerializer (handles password hashing, validation)
        - list (admin): UserListSerializer (light + projects_count)
        - retrieve: UserDetailSerializer (includes embedded projects list)
        """
        if self.action == "list":
            return UserListSerializer
        if self.action == "retrieve":
            return UserDetailSerializer
        return UserSerializer

    def get_queryset(self):
        """
        Queryset rules:
        - staff: can see everyone
        - non-staff: can only see themselves

        Adds summary counters for both list + retrieve:
        - num_projects_owned
        - num_projects_added_as_contrib

        For admin list:
        - also annotate projects_count (existing behavior)
        """
        user = self.request.user

        base_qs = User.objects.all() \
            if user.is_staff \
            else User.objects.filter(id=user.id)

        # The summaries are in BOTH list and retrieve, so always annotated.
        qs = base_qs.annotate(
            num_projects_owned=Count("owned_projects", distinct=True),
            num_projects_added_as_contrib=Count(
                "project_memberships",
                filter=~Q(project_memberships__project__author_id=F("id")),
                distinct=True,
            ),
        )

        # Optimization: useful for retrieve (detail)
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch(
                    "owned_projects",
                    queryset=Project.objects.select_related("author").order_by("-updated_at"),
                ),
                Prefetch(
                    "contributed_projects",
                    queryset=Project.objects.select_related("author").order_by("-updated_at"),
                ),
            )

        if self.action == "list":
            return qs.annotate(
                projects_count=Count("contributed_projects", distinct=True)
            )

        return qs

