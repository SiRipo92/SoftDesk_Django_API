"""
Test suite for the projects application.

Covers:
- Project model behavior (e.g., __str__)
- Project creation behavior (author auto-added as contributor)
- Contributor creation rules (lookup by username/email, duplicates, invalid payloads)
- ProjectViewSet behavior:
  - list is scoped to current user's memberships
  - contributors_count annotation excludes owner
  - retrieve/update permissions
  - contributor management actions (list/add/remove)
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.projects.models import Contributor, Project

User = get_user_model()


def create_user(*, username: str, email: str) -> User:
    """
    Create a valid user with required fields for this project.

    Args:
        username (str): Username for the user.
        email (str): Email for the user.

    Returns:
        User: A persisted user instance.
    """
    return User.objects.create_user(
        username=username,
        email=email,
        password="password123",
        birth_date="1990-01-01",
    )


class ProjectModelTests(APITestCase):
    """Tests related to Project/Contributor model behavior."""

    def test_project_str_representation_returns_name(self):
        """
        Return project name as the string representation.

        This ensures __str__ is covered and remains stable for admin/UI usage.
        """
        user = create_user(username="author", email="author@test.com")

        project = Project.objects.create(
            name="Test Project",
            description="Desc",
            project_type="BACK_END",
            author=user,
        )

        self.assertEqual(str(project), "Test Project")


class ProjectCreateTests(APITestCase):
    """Tests covering project creation behavior via API."""

    def setUp(self):
        """Create an authenticated author user."""
        self.author = create_user(username="author", email="author@test.com")
        self.client.force_authenticate(self.author)

    def test_create_project_adds_author_as_contributor(self):
        """
        Create a project and ensure the author is automatically a contributor.
        """
        url = reverse("projects:projects-list")
        payload = {
            "name": "My Project",
            "description": "Desc",
            "project_type": "BACK_END",
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        project = Project.objects.get(
            name=payload["name"],
            author=self.author,
        )

        self.assertTrue(
            Contributor.objects.filter(project=project, user=self.author).exists()
        )


class ContributorActionTests(APITestCase):
    """Tests for contributor management actions (GET/POST contributors)."""

    def setUp(self):
        """
        Create a project with an author membership.

        Also creates a second user that can be added as contributor.
        """
        self.author = create_user(username="author", email="author@test.com")
        self.bob = create_user(username="bob", email="bob@test.com")
        self.project = Project.objects.create(
            name="Project",
            description="Desc",
            project_type="BACK_END",
            author=self.author,
        )

        # Ensure author membership exists (mirrors serializer behavior).
        Contributor.objects.create(
            project=self.project,
            user=self.author,
            added_by=self.author,
        )

        self.contributors_url = reverse(
            "projects:projects-contributors", kwargs={"pk": self.project.pk}
        )

    def test_add_contributor_by_username_succeeds(self):
        """
        Add a contributor using username lookup.

        Covers:
        - ContributorCreateSerializer.validate() username branch
        - ContributorCreateSerializer.create()
        - View contributors POST path
        """
        self.client.force_authenticate(self.author)

        response = self.client.post(
            self.contributors_url,
            {"username": "bob"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertTrue(
            Contributor.objects.filter(project=self.project, user=self.bob).exists()
        )

    def test_add_contributor_by_email_succeeds(self):
        """
        Add a contributor using email lookup.

        Covers:
        - ContributorCreateSerializer.validate() email branch
        """
        self.client.force_authenticate(self.author)

        response = self.client.post(
            self.contributors_url,
            {"email": "bob@test.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertTrue(
            Contributor.objects.filter(project=self.project, user=self.bob).exists()
        )

    def test_add_contributor_rejects_missing_lookup_keys(self):
        """
        Reject payload that provides neither username nor email.

        Covers:
        - validate_exactly_one_provided error branch -> DRF 400
        """
        self.client.force_authenticate(self.author)

        response = self.client.post(self.contributors_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_contributor_rejects_both_username_and_email(self):
        """
        Reject payload that provides both username and email.

        Covers:
        - validate_exactly_one_provided "both provided" branch -> DRF 400
        """
        self.client.force_authenticate(self.author)

        response = self.client.post(
            self.contributors_url,
            {"username": "bob", "email": "bob@test.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_contributor_rejects_unknown_user(self):
        """
        Reject contributor addition when username/email cannot be resolved.

        Covers:
        - "Utilisateur introuvable." branch
        """
        self.client.force_authenticate(self.author)

        response = self.client.post(
            self.contributors_url,
            {"username": "does-not-exist"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_contributor_rejects_duplicates(self):
        """
        Reject adding the same user twice as contributor.

        Covers:
        - duplicate membership exists() branch -> DRF 400
        """
        self.client.force_authenticate(self.author)

        Contributor.objects.create(
            project=self.project,
            user=self.bob,
            added_by=self.author,
        )

        response = self.client.post(
            self.contributors_url,
            {"username": "bob"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_author_contributor_cannot_add_contributors(self):
        """
        A non-author contributor should be forbidden from adding contributors.

        Covers:
        - get_permissions() branch for contributors POST -> IsProjectAuthor
        """
        # Make bob a contributor first
        Contributor.objects.create(
            project=self.project,
            user=self.bob,
            added_by=self.author,
        )
        self.client.force_authenticate(self.bob)

        response = self.client.post(
            self.contributors_url,
            {"username": "author"},  # doesn't matter; should fail on permission first
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_contributors_lists_memberships(self):
        """
        GET contributors returns membership rows for the project.

        Covers:
        - contributors GET branch in the view
        """
        Contributor.objects.create(
            project=self.project,
            user=self.bob,
            added_by=self.author,
        )
        self.client.force_authenticate(self.author)

        response = self.client.get(self.contributors_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # View currently returns ALL memberships including the owner membership.
        self.assertGreaterEqual(len(response.data), 2)


class ProjectViewSetBehaviorTests(APITestCase):
    """
    Tests covering list scoping, annotation,
    retrieve/update permissions, and removal.
    """

    def setUp(self):
        """Create users and a project with memberships."""
        self.author = create_user(username="author", email="author@test.com")
        self.bob = create_user(username="bob", email="bob@test.com")
        self.charlie = create_user(username="charlie", email="charlie@test.com")

        self.project = Project.objects.create(
            name="Project",
            description="Desc",
            project_type="BACK_END",
            author=self.author,
        )

        Contributor.objects.create(
            project=self.project,
            user=self.author,
            added_by=self.author
        )
        Contributor.objects.create(
            project=self.project,
            user=self.bob,
            added_by=self.author
        )

        self.list_url = reverse("projects:projects-list")
        self.detail_url = reverse(
            "projects:projects-detail",
            kwargs={"pk": self.project.pk}
        )
        self.remove_bob_url = reverse(
            "projects:projects-remove-contributor",
            kwargs={"pk": self.project.pk, "user_id": self.bob.pk},
        )
        self.remove_author_url = reverse(
            "projects:projects-remove-contributor",
            kwargs={"pk": self.project.pk, "user_id": self.author.pk},
        )

    def test_list_is_scoped_to_current_user_memberships(self):
        """
        List returns only projects where request.user is a contributor.

        Covers:
        - get_queryset() membership scoping logic (Exists filter)
        """
        # Bob is a contributor -> should see project
        self.client.force_authenticate(self.bob)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        # Charlie is NOT a contributor -> should see none
        self.client.force_authenticate(self.charlie)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_list_contributors_count_excludes_owner(self):
        """
        List annotation contributors_count excludes the project owner.

        For this setup:
        - memberships: author + bob
        - contributors_count should be 1 (bob only)
        """
        self.client.force_authenticate(self.author)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data[0]["contributors_count"], 1)

    def test_retrieve_requires_contributor_membership(self):
        """
        Retrieve should be allowed for contributors and blocked for non-members.

        Covers:
        - retrieve permission path (IsProjectContributor)
        - queryset scoping causing 404 for non-members
        """
        # Contributor can retrieve
        self.client.force_authenticate(self.bob)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Non-contributor gets 404 because project isn't in scoped queryset
        self.client.force_authenticate(self.charlie)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_requires_author(self):
        """
        Only the project author can update.

        Covers:
        - get_permissions() update/partial_update branch (IsProjectAuthor)
        """
        patch_payload = {"description": "Updated desc"}

        # Non-author contributor should be forbidden
        self.client.force_authenticate(self.bob)
        response = self.client.patch(self.detail_url, patch_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Author can update
        self.client.force_authenticate(self.author)
        response = self.client.patch(self.detail_url, patch_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.project.refresh_from_db()
        self.assertEqual(self.project.description, "Updated desc")

    def test_author_can_remove_contributor(self):
        """
        Author can remove a contributor membership row.

        Covers:
        - remove_contributor action success path
        """
        self.client.force_authenticate(self.author)
        response = self.client.delete(self.remove_bob_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(
            Contributor.objects.filter(project=self.project, user=self.bob).exists()
        )

    def test_non_author_cannot_remove_contributor(self):
        """
        Non-author contributor cannot remove contributors.

        Covers:
        - remove_contributor permissions (IsProjectAuthor)
        """
        self.client.force_authenticate(self.bob)
        response = self.client.delete(self.remove_bob_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_remove_author_membership(self):
        """
        Attempting to remove the author should return HTTP 400.

        Covers:
        - 'prevent owner removal' branch in remove_contributor
        """
        self.client.force_authenticate(self.author)
        response = self.client.delete(self.remove_author_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_contributor_returns_404_for_missing_membership(self):
        """
        Removing a user that is not a contributor returns 404.

        Covers:
        - get_object_or_404 branch in remove_contributor
        """
        # Charlie is not a contributor; try removing them.
        remove_charlie_url = reverse(
            "projects:projects-remove-contributor",
            kwargs={"pk": self.project.pk, "user_id": self.charlie.pk},
        )

        self.client.force_authenticate(self.author)
        response = self.client.delete(remove_charlie_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
