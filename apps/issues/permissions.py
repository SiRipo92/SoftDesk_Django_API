"""
Issues app permissions.

This module provides app-scoped aliases for common permissions
so views can remain explicit (Issue-specific wording) without
duplicating shared logic.
"""

from __future__ import annotations

from common.permissions import IsAuthorOrReadOnly


class IsIssueAuthor(IsAuthorOrReadOnly):
    """
    Allow write operations only for the Issue author (or staff).

    Notes:
    - Inherits staff override behavior from common.permissions.IsAuthorOrReadOnly.
    - IssueViewSet uses this for update/delete and assignee mutations.
    """

    message = (
        "Seul l'auteur de l'issue (ou un administrateur) peut effectuer cette action."
    )
