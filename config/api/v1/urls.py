"""
Routage API versionné (v1).

Toutes les routes déclarées ici seront accessibles sous /api/v1/
car elles sont incluses par config/urls.py.
"""

from django.urls import include, path

urlpatterns = [
    # For login, logout, and token management
    path("auth/", include(("apps.auth.urls", "auth"), namespace="auth")),
    # For user related methods (GET, POST, PATCH, DELETE)
    path("", include(("apps.users.urls", "users"), namespace="users")),
    # Module Projects (projects + contributors)
    path("", include(("apps.projects.urls", "projects"), namespace="projects")),

    # Issues listing (tied to the user that's logged in)
    path("", include(("apps.issues.urls", "issues"), namespace="issues")),
]
