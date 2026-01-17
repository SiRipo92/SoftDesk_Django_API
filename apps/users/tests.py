"""
Test suite for the users application.

Covers:
- User model validation and derived properties
- User serializers per action (create, list, retrieve)
- Custom permission logic (IsSelfOrAdmin)
- UserViewSet queryset scoping and annotations
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APITestCase

from apps.projects.models import Project
from apps.users.permissions import IsSelfOrAdmin
from apps.users.serializers import (
    UserProjectSummarySerializer,
    UserSerializer,
)

User = get_user_model()


class UserModelTests(APITestCase):
    """Tests related to the User model."""

    def test_user_clean_enforces_minimum_age(self):
        """
        Raise ValidationError when birth_date violates minimum age rule.
        """
        too_young_date = date.today() - timedelta(days=10 * 365)

        user = User(
            username="too_young",
            email="young@example.com",
            birth_date=too_young_date,
        )

        with self.assertRaises(DjangoValidationError):
            user.full_clean()

    def test_age_property_is_computed_from_birth_date(self):
        """
        Compute age dynamically from birth_date.
        """
        birth_date = date.today() - timedelta(days=30 * 365)
        user = User.objects.create_user(
            username="adult",
            email="adult@example.com",
            birth_date=birth_date,
            password="StrongPassword123!",
        )

        self.assertGreaterEqual(user.age, 29)
        self.assertLessEqual(user.age, 31)


class UserSerializerTests(APITestCase):
    """Tests for user serializers."""

    def test_user_serializer_rejects_invalid_birth_date(self):
        """
        Raise DRF ValidationError for invalid birth_date input.
        """
        payload = {
            "username": "invalid_birth",
            "email": "invalid@example.com",
            "password": "StrongPassword123!",
            "birth_date": date.today().isoformat(),
        }

        serializer = UserSerializer(data=payload)

        with self.assertRaises(DRFValidationError):
            serializer.is_valid(raise_exception=True)

    def test_user_serializer_hashes_password_on_create(self):
        """
        Hash password before saving user instance.
        """
        payload = {
            "username": "hashed_user",
            "email": "hash@example.com",
            "password": "StrongPassword123!",
            "birth_date": "1995-01-01",
        }

        serializer = UserSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        self.assertNotEqual(user.password, payload["password"])
        self.assertTrue(user.check_password(payload["password"]))


class IsSelfOrAdminPermissionTests(APITestCase):
    """Tests for the IsSelfOrAdmin permission class."""

    def setUp(self):
        """Create users for permission tests."""
        self.user = User.objects.create_user(
            username="user",
            email="user@example.com",
            password="password123",
            birth_date="1990-01-01",
        )

        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="password123",
            birth_date="1990-01-01",
        )

        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass",
            birth_date="1980-01-01",
        )

    def test_user_has_permission_on_self(self):
        """
        Allow access when user accesses own object.
        """
        permission = IsSelfOrAdmin()
        request = type("Request", (), {"user": self.user})()

        self.assertTrue(permission.has_object_permission(request, None, self.user))

    def test_user_is_denied_access_to_others(self):
        """
        Deny access when user accesses another user.
        """
        permission = IsSelfOrAdmin()
        request = type("Request", (), {"user": self.user})()

        self.assertFalse(
            permission.has_object_permission(request, None, self.other_user)
        )

    def test_admin_has_permission_on_any_user(self):
        """
        Allow admin access to any user object.
        """
        permission = IsSelfOrAdmin()
        request = type("Request", (), {"user": self.admin})()

        self.assertTrue(
            permission.has_object_permission(request, None, self.other_user)
        )


class UserViewSetTests(APITestCase):
    """Tests for UserViewSet behavior."""

    def setUp(self):
        """Create users for API tests."""
        self.user = User.objects.create_user(
            username="user",
            email="user@example.com",
            password="password123",
            birth_date="1990-01-01",
        )

        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="password123",
            birth_date="1990-01-01",
        )

        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass",
            birth_date="1980-01-01",
        )

    def test_non_admin_cannot_retrieve_other_user(self):
        """
        Return 404 when non-admin tries to retrieve another user.
        """
        self.client.force_authenticate(user=self.user)

        url = reverse("users:users-detail", kwargs={"pk": self.other_user.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_can_list_users(self):
        """
        Allow admin to list all users.
        """
        self.client.force_authenticate(user=self.admin)

        url = reverse("users:users-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_user_list_uses_user_list_serializer_fields(self):
        """
        Return lightweight fields for admin user list.
        """
        self.client.force_authenticate(user=self.admin)

        url = reverse("users:users-list")
        response = self.client.get(url)

        first_item = response.data[0]

        self.assertIn("projects_count", first_item)
        self.assertIn("num_projects_owned", first_item)
        self.assertNotIn("owned_projects", first_item)

    def test_user_detail_uses_user_detail_serializer_fields(self):
        """
        Return detailed fields including embedded projects on retrieve.
        """
        self.client.force_authenticate(user=self.admin)

        url = reverse("users:users-detail", kwargs={"pk": self.user.pk})
        response = self.client.get(url)

        self.assertIn("owned_projects", response.data)
        self.assertIn("contributed_projects", response.data)
        self.assertIn("num_projects_owned", response.data)

    def test_user_can_delete_self(self):
        """
        Allow user to delete own account.
        """
        self.client.force_authenticate(user=self.user)

        url = reverse("users:users-detail", kwargs={"pk": self.user.pk})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class UserSerializerEdgeCaseTests(APITestCase):
    """Edge-case tests for UserSerializer create and update methods."""

    def setUp(self):
        """Create a base user for update tests."""
        self.user = User.objects.create_user(
            username="base_user",
            email="base@example.com",
            password="InitialPassword123!",
            birth_date="1990-01-01",
        )

    def test_create_user_without_password_raises_validation_error(self):
        """
        Raise ValidationError when creating a user without a password.
        """
        payload = {
            "username": "nopassword",
            "email": "nopassword@example.com",
            "birth_date": "1995-01-01",
        }

        serializer = UserSerializer(data=payload)

        serializer.is_valid(raise_exception=True)

        with self.assertRaises(DRFValidationError):
            serializer.save()

    def test_update_user_without_password(self):
        """
        Update user fields without changing password.
        """
        old_password_hash = self.user.password

        serializer = UserSerializer(
            instance=self.user,
            data={"first_name": "Updated"},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.password, old_password_hash)

    def test_update_user_with_new_password(self):
        """
        Update user password when password is provided.
        """
        serializer = UserSerializer(
            instance=self.user,
            data={"password": "NewSecurePassword123!"},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        self.assertTrue(user.check_password("NewSecurePassword123!"))

    def test_update_user_raises_validation_error_from_model(self):
        """
        Convert Django ValidationError into DRF ValidationError on update.
        """
        serializer = UserSerializer(
            instance=self.user,
            data={"birth_date": date.today().isoformat()},
            partial=True,
        )

        with self.assertRaises(DRFValidationError):
            serializer.is_valid(raise_exception=True)
            serializer.save()


class UserProjectSummarySerializerTests(APITestCase):
    """Tests for UserProjectSummarySerializer."""

    def setUp(self):
        """Create project with author."""
        self.user = User.objects.create_user(
            username="author",
            email="author@example.com",
            password="password123",
            birth_date="1990-01-01",
        )

        self.project = Project.objects.create(
            name="Test Project",
            description="Test description",
            project_type="BACK_END",
            author=self.user,
        )

    def test_project_summary_serialization(self):
        """
        Serialize project summary fields correctly.
        """
        serializer = UserProjectSummarySerializer(self.project)
        data = serializer.data

        self.assertEqual(data["author_id"], self.user.id)
        self.assertEqual(data["author_username"], self.user.username)
