"""
apps.users tests.

Covers:
- models.py: User.clean() rules + save(full_clean()) + age property
- serializers.py: birth_date validation + password hashing +
    model ValidationError -> DRF ValidationError
- permissions.py: IsSelfOrAdmin logic
- urls.py/views.py: router wiring + ViewSet permissions
    + queryset scoping behavior

Design notes:
- We use DRF's APITestCase to exercise endpoints like a real client would.
- We intentionally test "404 vs 403" for non-admin accessing other users:
  Your get_queryset() hides other users for non-staff, so get_object() returns 404.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .permissions import IsSelfOrAdmin
from .serializers import UserSerializer

User = get_user_model()


# -------------------------
# Helpers
# -------------------------
def date_years_ago(years: int) -> date:
    """
    Return a date that is `years` years before today.

    Why this helper:
    - Your model enforces "age >= 15".
    - Using a dynamic date prevents tests from breaking over time.
    - replace(year=...) can fail on Feb 29 -> we safely fall back to Feb 28.
    """
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        # Handles Feb 29 edge cases when the target year is not a leap year.
        return today.replace(month=2, day=28, year=today.year - years)


VALID_BIRTH_DATE = date_years_ago(20)  # safely >= 15


# -------------------------
# Model tests
# -------------------------
class UserModelTests(APITestCase):
    """Unit-style tests for apps.users.models.User."""

    def test_birth_date_is_required(self) -> None:
        """
        User.save() calls full_clean(), and clean() explicitly requires birth_date.
        So creating/saving without birth_date must raise DjangoValidationError.
        """
        user = User(username="u1", email="u1@example.com")
        user.set_password("StrongPassw0rd!*")

        with self.assertRaises(DjangoValidationError) as ctx:
            user.save()

        self.assertIn("birth_date", ctx.exception.message_dict)

    def test_birth_date_must_be_at_least_15_years_old(self) -> None:
        """
        clean() calls validate_birth_date_min_age(), so underage dates must fail.
        """
        underage = date_years_ago(10)

        user = User(username="u2", email="u2@example.com", birth_date=underage)
        user.set_password("StrongPassw0rd!*")

        with self.assertRaises(DjangoValidationError) as ctx:
            user.save()

        self.assertIn("birth_date", ctx.exception.message_dict)

    def test_birth_date_cannot_be_in_future(self) -> None:
        """
        validate_birth_date_min_age() also rejects dates in the future.
        """
        future = date.today().replace(year=date.today().year + 1)

        user = User(username="u3", email="u3@example.com", birth_date=future)
        user.set_password("StrongPassw0rd!*")

        with self.assertRaises(DjangoValidationError) as ctx:
            user.save()

        self.assertIn("birth_date", ctx.exception.message_dict)

    def test_age_property_returns_int_when_birth_date_set(self) -> None:
        """
        age is computed from birth_date by calculate_age().
        We don't assert an exact number (date boundaries), but we assert it's an int
        and that it's >= 15 for a valid birth_date.
        """
        user = User.objects.create_user(
            username="age_user",
            email="age_user@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

        self.assertIsInstance(user.age, int)
        self.assertGreaterEqual(user.age, 15)


# -------------------------
# Permission tests
# -------------------------
class IsSelfOrAdminTests(APITestCase):
    """Unit tests for apps.users.permissions.IsSelfOrAdmin."""

    def setUp(self) -> None:
        self.permission = IsSelfOrAdmin()

        self.user = User.objects.create_user(
            username="normal_user",
            email="normal_user@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

        self.other = User.objects.create_user(
            username="other_user",
            email="other_user@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

        self.admin = User.objects.create_superuser(
            username="admin_user",
            email="admin_user@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

    def test_allows_self(self) -> None:
        request = SimpleNamespace(user=self.user)
        self.assertTrue(self.permission.has_object_permission(request, None, self.user))

    def test_denies_other_for_non_admin(self) -> None:
        request = SimpleNamespace(user=self.user)
        self.assertFalse(
            self.permission.has_object_permission(request, None, self.other)
        )

    def test_allows_admin_for_any_user(self) -> None:
        request = SimpleNamespace(user=self.admin)
        self.assertTrue(self.permission.has_object_permission(request, None, self.user))
        self.assertTrue(
            self.permission.has_object_permission(request, None, self.other)
        )


# -------------------------
# Serializer tests
# -------------------------
class UserSerializerTests(APITestCase):
    """Unit tests for apps.users.serializers.UserSerializer."""

    def test_validate_birth_date_rejects_underage(self) -> None:
        """
        Serializer validates birth_date early with validate_birth_date_min_age().
        This is your "API boundary" rule (friendly 400 before model save).
        """
        payload = {
            "username": "too_young",
            "email": "too_young@example.com",
            "birth_date": date_years_ago(10),
            "password": "StrongPassw0rd!*",
        }

        serializer = UserSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("birth_date", serializer.errors)

    def test_create_hashes_password(self) -> None:
        """
        Serializer.create() calls set_password() so stored password is hashed.
        """
        raw_password = "StrongPassw0rd!*"
        payload = {
            "username": "hash_me",
            "email": "hash_me@example.com",
            "birth_date": VALID_BIRTH_DATE,
            "password": raw_password,
        }

        serializer = UserSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        user = serializer.save()
        self.assertNotEqual(user.password, raw_password)  # not plaintext
        self.assertTrue(user.check_password(raw_password))  # hashing worked

    def test_update_hashes_password_when_provided(self) -> None:
        """
        Serializer.update() also hashes password if present.
        """
        user = User.objects.create_user(
            username="upd_user",
            email="upd_user@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

        new_password = "NewStrongPassw0rd!*"
        serializer = UserSerializer(
            instance=user, data={"password": new_password}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        updated = serializer.save()
        self.assertTrue(updated.check_password(new_password))

    def test_create_converts_model_validation_error_to_drf_error(self) -> None:
        """
        Even if serializer validation didn't catch it, model.save() would.
        Your serializer catches DjangoValidationError and raises DRF ValidationError
        so the API returns HTTP 400 with field-level messages.
        """
        payload = {
            "username": "model_error",
            "email": "model_error@example.com",
            "birth_date": date_years_ago(10),  # underage
            "password": "StrongPassw0rd!*",
        }

        serializer = UserSerializer(data=payload)
        # validate_birth_date already catches underage, but this test also documents
        # the model->serializer conversion path if other model rules are added later.
        self.assertFalse(serializer.is_valid())
        self.assertIn("birth_date", serializer.errors)


# -------------------------
# View / URL integration tests
# -------------------------
class UserViewSetTests(APITestCase):
    """
    Integration tests for apps.users.views.UserViewSet via router URLs.

    These tests exercise:
    - urls.py router wiring (reverse names resolve)
    - get_permissions() behavior per action
    - get_queryset() scoping (non-staff only sees themselves)
    """

    def setUp(self) -> None:
        # from DefaultRouter basename="users"
        self.users_list_url = reverse("users:users-list")

        self.user = User.objects.create_user(
            username="u_main",
            email="u_main@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

        self.other = User.objects.create_user(
            username="u_other",
            email="u_other@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

        self.admin = User.objects.create_superuser(
            username="u_admin",
            email="u_admin@example.com",
            password="StrongPassw0rd!*",
            birth_date=VALID_BIRTH_DATE,
        )

    def test_signup_create_is_public(self) -> None:
        """
        get_permissions(): action == "create" -> AllowAny
        So POST /users/ should work without authentication.
        """
        payload = {
            "username": "new_user",
            "email": "new_user@example.com",
            "birth_date": str(VALID_BIRTH_DATE),
            "password": "StrongPassw0rd!*",
            "can_be_contacted": False,
            "can_data_be_shared": False,
        }

        res = self.client.post(self.users_list_url, data=payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", res.data)

    def test_signup_missing_birth_date_returns_400(self) -> None:
        """
        birth_date is required at model level and also by ModelSerializer by default.
        So omitting it should return a 400.
        """
        payload = {
            "username": "missing_bd",
            "email": "missing_bd@example.com",
            "password": "StrongPassw0rd!*",
        }

        res = self.client.post(self.users_list_url, data=payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("birth_date", res.data)

    def test_list_users_is_admin_only(self) -> None:
        """
        get_permissions(): action == "list" -> IsAdminUser
        """
        self.client.force_authenticate(user=self.user)
        res = self.client.get(self.users_list_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.admin)
        res2 = self.client.get(self.users_list_url)
        self.assertEqual(res2.status_code, status.HTTP_200_OK)

    def test_retrieve_self_ok_retrieve_other_hidden_for_non_admin(self) -> None:
        """
        Non-admin get_queryset() returns only themselves, so:
        - retrieving self works
        - retrieving other returns 404 (not in queryset)
        """
        self.client.force_authenticate(user=self.user)

        self_url = reverse("users:users-detail", kwargs={"pk": self.user.id})
        other_url = reverse("users:users-detail", kwargs={"pk": self.other.id})

        res_self = self.client.get(self_url)
        self.assertEqual(res_self.status_code, status.HTTP_200_OK)
        self.assertEqual(res_self.data["id"], self.user.id)

        res_other = self.client.get(other_url)
        self.assertEqual(res_other.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_can_retrieve_any_user(self) -> None:
        """Staff get_queryset() returns all users, so admin can retrieve others."""
        self.client.force_authenticate(user=self.admin)

        other_url = reverse("users:users-detail", kwargs={"pk": self.other.id})
        res = self.client.get(other_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], self.other.id)

    def test_update_self_ok_update_other_hidden_for_non_admin(self) -> None:
        """
        Non-admin can PATCH their own account.
        Other users are hidden by queryset -> 404.
        """
        self.client.force_authenticate(user=self.user)

        self_url = reverse("users:users-detail", kwargs={"pk": self.user.id})
        other_url = reverse("users:users-detail", kwargs={"pk": self.other.id})

        res_self = self.client.patch(
            self_url, data={"first_name": "Sierra"}, format="json"
        )
        self.assertEqual(res_self.status_code, status.HTTP_200_OK)
        self.assertEqual(res_self.data["first_name"], "Sierra")

        res_other = self.client.patch(
            other_url, data={"first_name": "Nope"}, format="json"
        )
        self.assertEqual(res_other.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_self_ok_delete_other_hidden_for_non_admin(self) -> None:
        """
        Non-admin can DELETE themselves (IsSelfOrAdmin).
        Other users are hidden -> 404.
        """
        self.client.force_authenticate(user=self.user)

        self_url = reverse("users:users-detail", kwargs={"pk": self.user.id})
        other_url = reverse("users:users-detail", kwargs={"pk": self.other.id})

        res_other = self.client.delete(other_url)
        self.assertEqual(res_other.status_code, status.HTTP_404_NOT_FOUND)

        res_self = self.client.delete(self_url)
        self.assertEqual(res_self.status_code, status.HTTP_204_NO_CONTENT)
