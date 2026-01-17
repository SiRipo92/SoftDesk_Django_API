from django.contrib import admin

from .models import Issue


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    """Admin configuration for Issue."""
    list_display = (
        "id",
        "title",
        "project",
        "author",
        "status",
        "priority",
        "tag",
        "created_at",
        "updated_at"
    )
    list_filter = ("status", "priority", "tag", "project")
    search_fields = (
        "title",
        "description",
        "project__name",
        "author__username",
        "author__email"
    )
    ordering = ("-updated_at",)
