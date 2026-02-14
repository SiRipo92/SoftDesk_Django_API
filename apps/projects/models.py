from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    # Import only for typing (avoids runtime import cycles)
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.db.models.manager import Manager

    from apps.issues.models import Issue
    from apps.users.models import User

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

    if TYPE_CHECKING:
        # Default manager injected by Django
        objects: "Manager[Project]"

        # FK id column injected by Django
        author_id: int

        # Runtime accessor for M2M is a manager-like object (supports .filter(), .exists(), etc.)
        contributors: "Manager[User]"

        # Reverse relation from Contributor.project (related_name="memberships")
        memberships: "Manager[Contributor]"

        # Reverse relation from Issue.project (related_name="issues")
        issues: "Manager[Issue]"

    def is_contributor(self, user: "AbstractBaseUser | None") -> bool:
        """Return True if the user is a contributor on this project."""
        if not user or not getattr(user, "pk", None):
            return False
        contributors_manager = cast(Any, self.contributors)
        return contributors_manager.filter(pk=user.pk).exists()

    def __str__(self) -> str:
        """Return a readable string representation for admin/debug."""
        return str(self.name)


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

    if TYPE_CHECKING:
        # Default manager injected by Django (for Contributor.objects)
        objects: "Manager[Contributor]"

        # Implicit FK id columns created by Django
        user_id: int
        project_id: int
        added_by_id: int

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
