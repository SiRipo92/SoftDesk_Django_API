"""
Users app tests.

These tests cover:
- User model basics.
- Signup contract (public create + email uniqueness).
- Access control for /users endpoints.
- Detail payload shape, including project previews.

Notes:
- /users/ list is admin-only.
- Non-admin users can only retrieve/update their own profile.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from apps.projects.models import Contributor, Project
from common.permissions import IsSelfOrAdmin

from .serializers import UserProjectPreviewSerializer, UserSerializer
from .views import UserViewSet

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
TEST_PASSWORD = "TestPass123!"
DEFAULT_BIRTH_DATE = date(1990, 1, 1)


def years_ago(years: int) -> date:
    """
    Return a date roughly `years` years ago, safe for leap years.

    We avoid naive timedelta arithmetic because it becomes flaky around
    leap days. Using date.replace() is deterministic, with a fallback when
    the current date is Feb 29.
    """
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        # Example: Feb 29 -> Feb 28 on non-leap years.
        return today.replace(month=2, day=28, year=today.year - years)


def create_user(
    *,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = TEST_PASSWORD,
    birth_date: date = DEFAULT_BIRTH_DATE,
    **extra_fields: Any,
) -> User:
    """
    Central user factory for this module.

    Why this exists:
    - User.save() calls full_clean(), so missing birth_date raises ValidationError.
    - Keeping defaults here prevents test breakage when the model gets stricter.
    """
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
        **extra_fields,
    )


def create_admin(
    *,
    username: str = "admin",
    email: str = "admin@example.com",
    password: str = TEST_PASSWORD,
    birth_date: date = DEFAULT_BIRTH_DATE,
    **extra_fields: Any,
) -> User:
    """Factory for staff/superuser accounts."""
    return User.objects.create_superuser(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
        **extra_fields,
    )


def extract_results(data: Any) -> list[dict[str, Any]]:
    """
    Normalize list responses.

    DRF returns either:
    - a list (no pagination), or
    - a dict with a "results" list (pagination enabled).
    """
    if isinstance(data, dict) and "results" in data:
        return list(data["results"])
    if isinstance(data, list):
        return list(data)
    raise AssertionError(f"Unexpected list payload shape: {type(data)!r}")


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class UserModelTests(APITestCase):
    def test_user_model_requires_birth_date(self) -> None:
        """User.save() runs full_clean(), so birth_date=None must fail."""
        with self.assertRaises(DjangoValidationError):
            create_user(birth_date=None)  # type: ignore[arg-type]

    def test_age_property_is_computed_from_birth_date(self) -> None:
        """
        age is a derived property (computed from birth_date).

        We assert a loose range to avoid flakiness around birthdays.
        """
        user = create_user(birth_date=years_ago(30))
        self.assertIsNotNone(user.age)
        self.assertTrue(29 <= user.age <= 31)


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


class UserSerializerTests(APITestCase):
    def setUp(self) -> None:
        """
        Prepare a valid payload used across UserSerializer creation tests.

        birth_date is generated via years_ago() to avoid hard-coding
        a date that could become invalid due to validator changes.
        """
        self.valid_data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": TEST_PASSWORD,
            "birth_date": years_ago(30).isoformat(),
        }

    def test_user_serializer_creates_user(self) -> None:
        """Serializer.save() should create a User instance with the given fields."""
        serializer = UserSerializer(data=self.valid_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.username, self.valid_data["username"])
        self.assertEqual(user.email, self.valid_data["email"])
        self.assertTrue(user.check_password(self.valid_data["password"]))

    def test_user_serializer_rejects_invalid_birth_date(self) -> None:
        """Serializer should reject birth_date values that fail min-age validation."""
        # Too recent -> should fail the min-age validator.
        invalid_data = self.valid_data.copy()
        invalid_data["birth_date"] = years_ago(1).isoformat()

        serializer = UserSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("birth_date", serializer.errors)

    def test_user_serializer_hashes_password_on_create(self) -> None:
        """Password must be hashed on create (stored value differs from input)."""
        serializer = UserSerializer(data=self.valid_data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        self.assertNotEqual(user.password, self.valid_data["password"])
        self.assertTrue(user.check_password(self.valid_data["password"]))


class UserSerializerProjectSummaryTests(APITestCase):
    def setUp(self) -> None:
        """
        Create a user and a project to validate the project preview serializer.

        The setup ensures:
        - a Project exists
        - the user is linked via Contributor (membership row)
        """
        self.user = create_user(username="user", email="user@example.com")
        self.project = Project.objects.create(
            name="Test Project",
            description="Test Description",
            project_type="BACK_END",
            author=self.user,
        )
        Contributor.objects.create(
            project=self.project,
            user=self.user,
            added_by=self.user,
        )

    def test_project_summary_serializer(self) -> None:
        """
        Project preview serializer should expose stable fields plus issues_count.

        issues_count is annotated at query time and must appear in the payload.
        """
        project = (
            Project.objects.filter(id=self.project.id)
            .select_related("author")
            .annotate(issues_count=Count("issues", distinct=True))
            .get()
        )

        serializer = UserProjectPreviewSerializer(project)
        data = serializer.data

        self.assertEqual(data["id"], project.id)
        self.assertEqual(data["name"], project.name)
        self.assertEqual(data["owner_username"], self.user.username)
        self.assertIn("issues_count", data)
        self.assertEqual(data["issues_count"], 0)


class UserSerializerEdgeCaseTests(APITestCase):
    def test_create_user_without_password_raises_error(self) -> None:
        """Creating a user without a password should fail serializer validation."""
        data = {
            "username": "user",
            "email": "user@example.com",
            "birth_date": years_ago(30).isoformat(),
        }
        serializer = UserSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)

    def test_update_user_rejects_invalid_birth_date(self) -> None:
        """
        Updating birth_date should also be validated.
        """
        user = create_user(username="user", email="user@example.com")

        serializer = UserSerializer(
            instance=user,
            data={"birth_date": years_ago(1).isoformat()},
            partial=True,
        )
        with self.assertRaises(DRFValidationError):
            serializer.is_valid(raise_exception=True)


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


class IsSelfOrAdminPermissionTests(APITestCase):
    def setUp(self) -> None:
        """
        Create a permission instance and two users for object-permission checks.

        This suite verifies IsSelfOrAdmin.has_object_permission() only.
        """
        self.permission = IsSelfOrAdmin()
        self.factory = RequestFactory()
        self.user = create_user(username="user", email="user@example.com")
        self.admin = create_admin()

    def test_user_can_access_own_object(self) -> None:
        """A user should pass object permission checks on their own profile."""
        request = self.factory.get("/")
        request.user = self.user

        self.assertTrue(self.permission.has_object_permission(request, None, self.user))

    def test_user_cannot_access_other_object(self) -> None:
        """A non-staff user should fail object permission checks for other users."""
        other_user = create_user(username="other", email="other@example.com")

        request = self.factory.get("/")
        request.user = self.user

        self.assertFalse(
            self.permission.has_object_permission(request, None, other_user)
        )

    def test_admin_can_access_any_object(self) -> None:
        """A staff user should pass object permission checks for any user object."""
        request = self.factory.get("/")
        request.user = self.admin

        self.assertTrue(self.permission.has_object_permission(request, None, self.user))


# ---------------------------------------------------------------------------
# ViewSet tests
# ---------------------------------------------------------------------------


class UserViewSetTests(APITestCase):
    def setUp(self) -> None:
        """
        Prepare a DRF request factory and common users for viewset tests.

        Users created:
        - regular user (self)
        - other user (used for forbidden access checks)
        - admin user (used for list access checks)
        """
        self.factory = APIRequestFactory()
        self.list_url = reverse("users:users-list")

        self.user = create_user(username="user", email="user@example.com")
        self.other_user = create_user(username="other", email="other@example.com")
        self.admin = create_admin()

    def test_admin_can_list_users(self) -> None:
        """Admin should be able to list users and receive annotated list fields."""
        request = self.factory.get(self.list_url)
        force_authenticate(request, user=self.admin)

        view = UserViewSet.as_view({"get": "list"})
        response = view(request)

        self.assertEqual(response.status_code, 200)

        results = extract_results(response.data)
        self.assertGreaterEqual(len(results), 2)
        self.assertIn("projects_count", results[0])

    def test_non_admin_cannot_list_users(self) -> None:
        """Non-admin users must be forbidden from accessing the users list."""
        request = self.factory.get(self.list_url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"get": "list"})
        response = view(request)

        self.assertEqual(response.status_code, 403)

    def test_user_can_retrieve_self(self) -> None:
        """A user should be able to retrieve their own detail payload."""
        url = reverse("users:users-detail", kwargs={"pk": self.user.id})
        request = self.factory.get(url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"get": "retrieve"})
        response = view(request, pk=self.user.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.user.id)
        self.assertEqual(response.data["num_projects_owned"], 0)
        self.assertEqual(response.data["num_projects_added_as_contrib"], 0)
        self.assertEqual(response.data["owned_projects_preview"], [])
        self.assertEqual(response.data["contributed_projects_preview"], [])

    def test_non_admin_cannot_retrieve_other_user(self) -> None:
        """A non-admin user must be forbidden from retrieving another user's profile."""
        url = reverse("users:users-detail", kwargs={"pk": self.other_user.id})
        request = self.factory.get(url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"get": "retrieve"})
        response = view(request, pk=self.other_user.id)

        # Non-admin queryset hides other users -> 403
        self.assertEqual(response.status_code, 403)

    def test_user_can_delete_self(self) -> None:
        """A user should be able to delete their own account."""
        url = reverse("users:users-detail", kwargs={"pk": self.user.id})
        request = self.factory.delete(url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"delete": "destroy"})
        response = view(request, pk=self.user.id)

        self.assertEqual(response.status_code, 204)
