from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.issues.models import Issue


class Comment(models.Model):
    """
    Stores a comment attached to a single issue.

    Rules enforced here:
    - The author must be a contributor of the issue's project.
    """

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    description = models.TextField(
        max_length=500,
        blank=False
    )

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    issue = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="comments",
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments_created"
    )

    def clean(self) -> None:
        """
        Validate cross-field business rules.

        If issue and author are set, ensure the author belongs to the
        issue's project contributors.
        """

        super.clean()

        if self.issue_id is None or self.author_id is None:
            return

        project = self.issue.project
        author = self.author

        if not project.is_contributor(author):
            raise ValidationError(
                {"author": "L'auteur doit être contributeur du projet."}
            )

    def save(self, *args, **kwargs) -> None:
        """Run validation before saving."""
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Readable label for admin/debug."""
        return f"{self.uuid}"
