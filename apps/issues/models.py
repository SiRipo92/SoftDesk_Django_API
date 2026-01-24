from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.projects.models import Project

# --------------------------------------------------
# Text field options (Priority, Tag, Status)
# --------------------------------------------------


class IssuePriority(models.TextChoices):
    """Priority levels available for an issue."""

    LOW = "LOW", "low"
    MEDIUM = "MEDIUM", "medium"
    HIGH = "HIGH", "high"


class IssueTag(models.TextChoices):
    """Category labels available for an Issue"""

    BUG = "BUG", "bug"
    FEATURE = "FEATURE", "feature"
    TASK = "TASK", "task"


class IssueStatus(models.TextChoices):
    """Workflow states available for an issue."""

    TODO = "TO DO", "To Do"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"


# --------------------------------------------------
# Model class for Issues
# --------------------------------------------------


class Issue(models.Model):
    """
    Stores an issue attached to a single project.

    Business rules:
    - The issue author must belong to the project's contributors list.

    Assignees are optional:
    - An issue can have zero, one, or many assigned users.
    - Stored via IssueAssignee through model to keep assignment metadata
      (assigned_at, assigned_by).
    """

    title = models.CharField(max_length=150)
    description = models.TextField(max_length=500, blank=True)

    # Optional: if not provided, the value will be an empty string ("").
    priority = models.CharField(
        max_length=15,
        choices=IssuePriority.choices,
        blank=True,
    )

    # Optional: single tag value (not a relation).
    tag = models.CharField(
        max_length=15,
        choices=IssueTag.choices,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=IssueStatus.choices,
        default=IssueStatus.TODO,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="issues",
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="issues_created",
    )

    # Optional: an issue can be assigned to multiple users.
    # Constraint "assignees must be contributors" is enforced in the serializer.
    # Use a through model to store assigned_at / assigned_by metadata.
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="IssueAssignee",
        through_fields=("issue", "user"),
        related_name="issues_assigned",
        blank=True,
    )

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        """
        Validate rules that depend on multiple fields.

        - If both project and author are set, verify the author is part of
          the project's contributors.
        """

        super().clean()

        # If one of these is missing, we can't validate the rule yet.
        if self.project_id is None or self.author_id is None:
            return

        if not self.project.is_contributor(self.author):
            raise ValidationError(
                {"author": "L'auteur doit être contributeur du projet."}
            )

    def save(self, *args, **kwargs) -> None:
        """
        Validate the model before saving.

        This ensures `clean()` is executed whenever an Issue is saved.
        """

        # full_clean calls field validation + clean()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Readable label for admin/debug."""
        return self.title


class IssueAssignee(models.Model):
    """
    Join model between Issue and User that stores assignment metadata.
    """

    issue = models.ForeignKey(
        "Issue",
        on_delete=models.CASCADE,
        related_name="assignee_links",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="issue_assignment_links",
    )

    # When the assignment was created
    assigned_at = models.DateTimeField(default=timezone.now, editable=False)

    # Who performed the assignment (actor). Nullable for backfill / imports.
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issue_assignments_created",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "user"],
                name="uniq_issue_assignee",
            )
        ]
        indexes = [
            models.Index(fields=["issue"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.issue_id} -> {self.user_id}"
