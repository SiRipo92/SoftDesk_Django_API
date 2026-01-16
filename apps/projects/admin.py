from __future__ import annotations

from django.contrib import admin

from .models import Contributor, Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "project_type", "author", "created_at", "updated_at")
    search_fields = ("name", "author__username", "author__email")
    list_filter = ("project_type", "created_at")
    ordering = ("-created_at",)


@admin.register(Contributor)
class ContributorAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "user", "added_by", "created_at")
    search_fields = (
        "project__name",
        "user__username",
        "user__email",
        "added_by__username",
        "added_by__email",
    )
    list_filter = ("created_at",)
    ordering = ("-created_at",)
