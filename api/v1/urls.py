"""
Routage API versionné (v1).

Toutes les routes déclarées ici seront accessibles sous /api/v1/
car elles sont incluses par config/urls.py.
"""

from django.urls import include, path

urlpatterns = [
    # Module Users (signup/login + refresh/logout + me)
    path("", include(("apps.users.urls", "users"), namespace="users")),
]