"""
URL configuration for config project that points to /admin backoffice
and api/v1/ routes.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # All API endpoints will live under /api/v1/
    path("api/v1/", include("config.api.v1.urls")),
]
