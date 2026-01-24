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

from typing import Any

from datetime import date
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory, force_authenticate
from django.db.models import Count
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.projects.models import Contributor, Project

from .permissions import IsSelfOrAdmin
from .serializers import (
    UserSerializer,
    UserProjectPreviewSerializer
)
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
        self.valid_data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": TEST_PASSWORD,
            "birth_date": years_ago(30).isoformat(),
        }

    def test_user_serializer_creates_user(self) -> None:
        serializer = UserSerializer(data=self.valid_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertEqual(user.username, self.valid_data["username"])
        self.assertEqual(user.email, self.valid_data["email"])
        self.assertTrue(user.check_password(self.valid_data["password"]))

    def test_user_serializer_rejects_invalid_birth_date(self) -> None:
        # Too recent -> should fail the min-age validator.
        invalid_data = self.valid_data.copy()
        invalid_data["birth_date"] = years_ago(1).isoformat()

        serializer = UserSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("birth_date", serializer.errors)

    def test_user_serializer_hashes_password_on_create(self) -> None:
        serializer = UserSerializer(data=self.valid_data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        self.assertNotEqual(user.password, self.valid_data["password"])
        self.assertTrue(user.check_password(self.valid_data["password"]))


class UserSerializerProjectSummaryTests(APITestCase):
    def setUp(self) -> None:
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

        Note:
        - This test checks the update path specifically.
        - If you consider it redundant with the create validation test above,
          you can remove it to shorten the suite.
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
        self.permission = IsSelfOrAdmin()
        self.factory = RequestFactory()
        self.user = create_user(username="user", email="user@example.com")
        self.admin = create_admin()

    def test_user_can_access_own_object(self) -> None:
        request = self.factory.get("/")
        request.user = self.user

        self.assertTrue(self.permission.has_object_permission(request, None, self.user))

    def test_user_cannot_access_other_object(self) -> None:
        other_user = create_user(username="other", email="other@example.com")

        request = self.factory.get("/")
        request.user = self.user

        self.assertFalse(
            self.permission.has_object_permission(request, None, other_user)
        )

    def test_admin_can_access_any_object(self) -> None:
        request = self.factory.get("/")
        request.user = self.admin

        self.assertTrue(self.permission.has_object_permission(request, None, self.user))


# ---------------------------------------------------------------------------
# ViewSet tests
# ---------------------------------------------------------------------------


class UserViewSetTests(APITestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.list_url = reverse("users:users-list")

        self.user = create_user(username="user", email="user@example.com")
        self.other_user = create_user(username="other", email="other@example.com")
        self.admin = create_admin()

    def test_admin_can_list_users(self) -> None:
        request = self.factory.get(self.list_url)
        force_authenticate(request, user=self.admin)

        view = UserViewSet.as_view({"get": "list"})
        response = view(request)

        self.assertEqual(response.status_code, 200)

        results = extract_results(response.data)
        self.assertGreaterEqual(len(results), 2)
        self.assertIn("projects_count", results[0])

    def test_non_admin_cannot_list_users(self) -> None:
        request = self.factory.get(self.list_url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"get": "list"})
        response = view(request)

        self.assertEqual(response.status_code, 403)

    def test_user_can_retrieve_self(self) -> None:
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
        url = reverse("users:users-detail", kwargs={"pk": self.other_user.id})
        request = self.factory.get(url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"get": "retrieve"})
        response = view(request, pk=self.other_user.id)

        # Non-admin queryset hides other users -> 404
        self.assertEqual(response.status_code, 404)

    def test_user_can_delete_self(self) -> None:
        url = reverse("users:users-detail", kwargs={"pk": self.user.id})
        request = self.factory.delete(url)
        force_authenticate(request, user=self.user)

        view = UserViewSet.as_view({"delete": "destroy"})
        response = view(request, pk=self.user.id)

        self.assertEqual(response.status_code, 204)
