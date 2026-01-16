"""
apps.projects tests.

Coverage targets:
- models.py:
  - Project.is_contributor()
  - Contributor unique constraint (user, project)
- serializers.py:
  - ProjectSerializer.create() author from request.user
  - ContributorCreateSerializer validation + membership creation
  - ContributorReadSerializer representation
- views.py (ProjectViewSet):
  - queryset visibility (contributors-only)
  - permissions for CRUD + contributor management actions
  - perform_create() adds author as contributor

Notes:
- Users require a valid birth_date (>= 15 years old) because the custom User
  model enforces validation in save() via full_clean().
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from .models import Contributor, Project
from .serializers import (
    ContributorCreateSerializer,
    ContributorReadSerializer,
    ProjectSerializer,
)

User = get_user_model()


def birth_date_adult() -> date:
    """
    Return a birth date safely >= 15 years old.

    Using a fixed date keeps tests deterministic.
    """
    return date(2000, 1, 1)


class ProjectModelTests(TestCase):
    """Unit tests for Project model helpers."""

    def setUp(self) -> None:
        """Create baseline users and a project with the owner as contributor."""
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.other = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.project = Project.objects.create(
            name="Project A",
            description="",
            project_type="BACK_END",
            author=self.owner,
        )
        Contributor.objects.create(
            project=self.project,
            user=self.owner,
            added_by=self.owner,
        )

    def test_is_contributor_true_for_member(self) -> None:
        """Project.is_contributor() returns True when user is a contributor."""
        Contributor.objects.create(
            project=self.project,
            user=self.other,
            added_by=self.owner,
        )
        self.assertTrue(self.project.is_contributor(self.other))

    def test_is_contributor_false_for_none_or_unsaved(self) -> None:
        """Project.is_contributor() returns False for None or unsaved user."""
        self.assertFalse(self.project.is_contributor(None))
        self.assertFalse(self.project.is_contributor(User()))


class ContributorModelTests(TestCase):
    """Unit tests for Contributor join model constraints."""

    def setUp(self) -> None:
        """Create baseline users and a project used for membership tests."""
        self.owner = User.objects.create_user(
            username="owner2",
            email="owner2@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.member = User.objects.create_user(
            username="member2",
            email="member2@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.project = Project.objects.create(
            name="Project B",
            description="",
            project_type="FRONT_END",
            author=self.owner,
        )

    def test_unique_constraint_user_project(self) -> None:
        """(user, project) membership must be unique."""
        Contributor.objects.create(
            project=self.project,
            user=self.member,
            added_by=self.owner,
        )
        with self.assertRaises(IntegrityError):
            Contributor.objects.create(
                project=self.project,
                user=self.member,
                added_by=self.owner,
            )


class ProjectSerializerTests(TestCase):
    """Tests for ProjectSerializer behavior."""

    def setUp(self) -> None:
        """Create a user and a request factory for serializer context."""
        self.user = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.factory = APIRequestFactory()

    def test_project_serializer_create_sets_author_from_request(self) -> None:
        """Author is derived from request.user, not from client payload."""
        request = self.factory.post("/projects/", {}, format="json")
        request.user = self.user

        serializer = ProjectSerializer(
            data={
                "name": "New Project",
                "description": "Desc",
                "project_type": "BACK_END",
            },
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        project = serializer.save()
        self.assertEqual(project.author_id, self.user.id)
        self.assertEqual(project.name, "New Project")

        rendered = ProjectSerializer(project).data
        self.assertEqual(rendered["author_id"], self.user.id)
        self.assertEqual(rendered["author_username"], self.user.username)


class ContributorCreateSerializerTests(TestCase):
    """Tests for ContributorCreateSerializer validation and create()."""

    def setUp(self) -> None:
        """Create project + users and add the owner as initial contributor."""
        self.owner = User.objects.create_user(
            username="proj_owner",
            email="proj_owner@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.target = User.objects.create_user(
            username="target_user",
            email="target_user@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.project = Project.objects.create(
            name="Project C",
            description="",
            project_type="IOS",
            author=self.owner,
        )
        Contributor.objects.create(
            project=self.project,
            user=self.owner,
            added_by=self.owner,
        )
        self.factory = APIRequestFactory()

    def test_requires_exactly_one_of_username_or_email(self) -> None:
        """Client must provide exactly one lookup key: username OR email."""
        request = self.factory.post("/fake", {}, format="json")
        request.user = self.owner

        serializer = ContributorCreateSerializer(
            data={},
            context={"request": request, "project": self.project},
        )
        self.assertFalse(serializer.is_valid())
        self.assertTrue(serializer.errors)

        serializer = ContributorCreateSerializer(
            data={"username": "x", "email": "x@example.com"},
            context={"request": request, "project": self.project},
        )
        self.assertFalse(serializer.is_valid())
        self.assertTrue(serializer.errors)

    def test_fails_if_user_not_found(self) -> None:
        """Unknown username/email must fail validation with friendly message."""
        request = self.factory.post("/fake", {}, format="json")
        request.user = self.owner

        serializer = ContributorCreateSerializer(
            data={"username": "does_not_exist"},
            context={"request": request, "project": self.project},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("Utilisateur introuvable.", str(serializer.errors))

    def test_fails_if_already_contributor(self) -> None:
        """Adding the same user twice to the same project must fail."""
        Contributor.objects.create(
            project=self.project,
            user=self.target,
            added_by=self.owner,
        )

        request = self.factory.post("/fake", {}, format="json")
        request.user = self.owner

        serializer = ContributorCreateSerializer(
            data={"username": self.target.username},
            context={"request": request, "project": self.project},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("déjà contributeur", str(serializer.errors))

    def test_creates_membership_with_added_by_from_request(self) -> None:
        """Membership added_by must always be request.user."""
        request = self.factory.post("/fake", {}, format="json")
        request.user = self.owner

        serializer = ContributorCreateSerializer(
            data={"username": self.target.username},
            context={"request": request, "project": self.project},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        membership = serializer.save()
        self.assertEqual(membership.project_id, self.project.id)
        self.assertEqual(membership.user_id, self.target.id)
        self.assertEqual(membership.added_by_id, self.owner.id)

        rendered = ContributorReadSerializer(membership).data
        self.assertEqual(rendered["user_id"], self.target.id)
        self.assertEqual(rendered["added_by_id"], self.owner.id)


class ProjectViewSetTests(APITestCase):
    """Integration tests for ProjectViewSet + router URLs."""

    def setUp(self) -> None:
        """Create users, a project, and baseline contributor memberships."""
        self.owner = User.objects.create_user(
            username="owner_api",
            email="owner_api@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.contributor = User.objects.create_user(
            username="contrib_api",
            email="contrib_api@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.stranger = User.objects.create_user(
            username="stranger_api",
            email="stranger_api@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )
        self.new_user = User.objects.create_user(
            username="new_user_api",
            email="new_user_api@example.com",
            password="StrongPassw0rd!*",
            birth_date=birth_date_adult(),
        )

        self.project = Project.objects.create(
            name="API Project",
            description="",
            project_type="ANDROID",
            author=self.owner,
        )

        # Author must be a contributor.
        Contributor.objects.create(
            project=self.project,
            user=self.owner,
            added_by=self.owner,
        )
        Contributor.objects.create(
            project=self.project,
            user=self.contributor,
            added_by=self.owner,
        )

        # Router names from DefaultRouter basename="projects", namespaced by app_name.
        self.projects_list_url = reverse("projects:projects-list")
        self.project_detail_url = reverse(
            "projects:projects-detail",
            kwargs={"pk": self.project.id},
        )
        self.contributors_url = reverse(
            "projects:projects-contributors",
            kwargs={"pk": self.project.id},
        )
        self.remove_contributor_url = reverse(
            "projects:projects-remove-contributor",
            kwargs={"pk": self.project.id, "user_id": self.contributor.id},
        )

    def test_list_requires_auth(self) -> None:
        """Unauthenticated access must be rejected."""
        res = self.client.get(self.projects_list_url)
        self.assertIn(
            res.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_list_only_returns_projects_where_user_is_contributor(self) -> None:
        """List endpoint returns only projects where request.user is contributor."""
        other_project = Project.objects.create(
            name="Other Project",
            description="",
            project_type="BACK_END",
            author=self.owner,
        )
        Contributor.objects.create(
            project=other_project,
            user=self.owner,
            added_by=self.owner,
        )

        self.client.force_authenticate(user=self.contributor)
        res = self.client.get(self.projects_list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        returned_ids = {p["id"] for p in res.data}
        self.assertIn(self.project.id, returned_ids)
        self.assertNotIn(other_project.id, returned_ids)

    def test_retrieve_as_contributor_ok(self) -> None:
        """Contributors can retrieve project details."""
        self.client.force_authenticate(user=self.contributor)
        res = self.client.get(self.project_detail_url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], self.project.id)

    def test_retrieve_as_non_contributor_is_404_due_to_queryset_filter(
        self,
    ) -> None:
        """
        Non-contributors get 404 because get_queryset() filters visibility.
        """
        self.client.force_authenticate(user=self.stranger)
        res = self.client.get(self.project_detail_url)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_only_author(self) -> None:
        """Only the project author can update."""
        patch_payload = {"name": "Renamed"}

        self.client.force_authenticate(user=self.contributor)
        res = self.client.patch(
            self.project_detail_url,
            data=patch_payload,
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        res = self.client.patch(
            self.project_detail_url,
            data=patch_payload,
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Renamed")

    def test_destroy_only_author(self) -> None:
        """Only the project author can delete the project."""
        self.client.force_authenticate(user=self.contributor)
        res = self.client.delete(self.project_detail_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        res = self.client.delete(self.project_detail_url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_create_project_adds_author_as_contributor(self) -> None:
        """perform_create() ensures author is also a contributor."""
        self.client.force_authenticate(user=self.owner)
        res = self.client.post(
            self.projects_list_url,
            data={
                "name": "Created Via API",
                "description": "",
                "project_type": "BACK_END",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        created = Project.objects.get(id=res.data["id"])
        self.assertEqual(created.author_id, self.owner.id)
        self.assertTrue(
            Contributor.objects.filter(project=created, user=self.owner).exists()
        )

    def test_contributors_get_allowed_for_contributors(self) -> None:
        """Any contributor can list contributors on the project."""
        self.client.force_authenticate(user=self.contributor)
        res = self.client.get(self.contributors_url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        user_ids = {row["user_id"] for row in res.data}

        self.assertIn(self.owner.id, user_ids)
        self.assertIn(self.contributor.id, user_ids)

    def test_contributors_post_author_only(self) -> None:
        """Only the author can add contributors."""
        payload = {"username": self.new_user.username}

        self.client.force_authenticate(user=self.contributor)
        res = self.client.post(self.contributors_url, data=payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        res = self.client.post(self.contributors_url, data=payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.assertTrue(
            Contributor.objects.filter(
                project=self.project, user=self.new_user
            ).exists()
        )

    def test_remove_contributor_author_only(self) -> None:
        """Only the author can remove contributors."""
        self.client.force_authenticate(user=self.contributor)
        res = self.client.delete(self.remove_contributor_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        res = self.client.delete(self.remove_contributor_url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(
            Contributor.objects.filter(
                project=self.project,
                user=self.contributor,
            ).exists()
        )

    def test_remove_contributor_cannot_remove_author(self) -> None:
        """
        Expected behavior: author cannot remove themselves from their project.

        This test requires a view-level guard in remove_contributor():
        if user_id == project.author_id -> return 400.
        """
        remove_author_url = reverse(
            "projects:projects-remove-contributor",
            kwargs={"pk": self.project.id, "user_id": self.owner.id},
        )

        self.client.force_authenticate(user=self.owner)
        res = self.client.delete(remove_author_url)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Impossible de retirer l'auteur", str(res.data))
