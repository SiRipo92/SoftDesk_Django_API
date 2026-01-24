"""
API V1 Routing.

All the routes declared here will be accessible under /api/v1/
because they're included in config/urls.py
"""

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework import permissions

urlpatterns = [
    # OpenAPI schema (JSON) - v1 scoped
    path(
        "schema/",
        SpectacularAPIView.as_view(permission_classes=[permissions.AllowAny]),
        name="schema",
    ),

    # Swagger UI - v1 scoped
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),

    # ReDoc - v1 scoped
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    # Auth / JWT
    path("auth/", include(("apps.auth.urls", "auth"), namespace="auth")),

    # API resources
    path("", include(("apps.users.urls", "users"), namespace="users")),
    path("", include(("apps.projects.urls", "projects"), namespace="projects")),
    path("", include(("apps.issues.urls", "issues"), namespace="issues")),
]