from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ProjectType(models.TextChoices):
    """Allowed values for a project's type/category."""

    BACK_END = "BACK_END", "Back-end"
    FRONT_END = "FRONT_END", "Front-end"
    IOS = "IOS", "iOS"
    ANDROID = "ANDROID", "Android"


class Project(models.Model):
    """Project resource.

    A Project is owned by an author (the creator) and can have multiple
    contributors (members) through the Contributor join model.

    Fields:
        name: Project name.
        description: Optional free-text description.
        created_at: Creation timestamp.
        updated_at: Last update timestamp (auto-updated).
        project_type: Enum-like value using ProjectType choices.
        author: Owner/creator of the project.
        contributors: Members of the project (Many-to-many via Contributor).
    """

    name = models.CharField(max_length=150, blank=False, null=False)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    project_type = models.CharField(max_length=20, choices=ProjectType.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        # user.owned_projects.all() -> projects created/owned by that user
        related_name="owned_projects",
    )

    # Many-to-many via Contributor join model (because we store metadata like added_by)
    contributors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="Contributor",
        # IMPORTANT: Contributor has TWO FKs to User (user + added_by).
        # We tell Django which FK is the "target" of this M2M.
        through_fields=("project", "user"),
        # user.contributed_projects.all() -> projects where user is a contributor
        related_name="contributed_projects",
        blank=True,
    )

    def is_contributor(self, user) -> bool:
        """Return True if the user is a contributor on this project."""
        if not user or not getattr(user, "pk", None):
            return False
        return self.contributors.filter(pk=user.pk).exists()

    def __str__(self) -> str:
        """Return a readable string representation for admin/debug."""
        return self.name


class Contributor(models.Model):
    """
    Contributor membership resource.

    This is the join model linking a user to a project, with metadata about
    who added them and when.

    Fields:
        user: The member user (the contributor being added).
        project: The project the user belongs to.
        added_by: The user who added this contributor (typically the project owner).
        created_at: Membership creation timestamp.

    Constraints:
        (user, project) must be unique to prevent duplicate memberships.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        # user.project_memberships.all() -> Contributor rows for that user
        related_name="project_memberships",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        # project.memberships.all() -> Contributor rows for that project
        related_name="memberships",
    )
    # who added this contributor (usually the project owner)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        # user.contributors_added.all() -> Contributor rows the user created (added)
        related_name="contributors_added",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        """Model constraints and metadata for Contributor."""

        constraints = [
            models.UniqueConstraint(
                fields=["user", "project"],
                name="uniq_contributor_user_project",
            )
        ]

    def __str__(self) -> str:
        """Return a readable string representation for admin/debug."""
        return f"{self.user_id} -> {self.project_id}"
