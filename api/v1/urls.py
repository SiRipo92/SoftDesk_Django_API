"""
Routage API versionné (v1).

Toutes les routes déclarées ici seront accessibles sous /api/v1/
car elles sont incluses par config/urls.py.
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Module Users (signup/login + refresh/logout + me)
    path("", include(("apps.users.urls", "users"), namespace="users")),

    # API docs
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]