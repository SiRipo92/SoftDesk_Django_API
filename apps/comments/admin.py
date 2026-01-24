from __future__ import annotations

from django.contrib import admin

from .models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """Admin configuration for Comment."""

    list_display = ("uuid", "issue", "author", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at", "issue__project")
    search_fields = ("uuid", "description", "author__username", "author__email")
    ordering = ("-updated_at",)
