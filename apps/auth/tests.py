"""
apps.auth tests.

Covers:
- POST /auth/login/ -> returns access + refresh
- POST /auth/refresh/ -> returns a new access token
- POST /auth/logout/ -> blacklists the provided refresh token

Why test third-party endpoints?
- login/refresh are provided by SimpleJWT, but we test them to ensure:
  1) our URLs are wired correctly
  2) our settings support the expected behavior (token rotation/blacklist)
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthEndpointsTests(APITestCase):
    """Integration tests for auth endpoints (JWT + logout blacklist behavior)."""

    def setUp(self) -> None:
        """
        Create a user for authentication tests.

        Notes:
        - TokenObtainPairView authenticates against the configured user model.
        - get_user_model() keeps tests compatible with a custom User model.
        """
        self.password = "StrongPassw0rd!*"
        self.user = User.objects.create_user(
            username="test_user",
            email="test_user@example.com",
            password=self.password,
            birth_date=date(2000, 1, 1),
        )

        # URL names come from apps/auth/urls.py (app_name="auth")
        self.login_url = reverse("auth:login")
        self.refresh_url = reverse("auth:refresh")
        self.logout_url = reverse("auth:logout")

    def _login(self) -> dict:
        """
        Helper: log in and return the token pair.
        Keeps tests focused and avoids duplicate code.
        """
        res = self.client.post(
            self.login_url,
            data={"username": self.user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        return res.data

    def test_login_returns_access_and_refresh(self) -> None:
        """POST /auth/login/ returns a token pair."""
        data = self._login()
        self.assertTrue(data["access"])
        self.assertTrue(data["refresh"])

    def test_refresh_returns_new_access(self) -> None:
        """POST /auth/refresh/ with a valid refresh returns an access token."""
        tokens = self._login()

        res = self.client.post(
            self.refresh_url,
            data={"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)
        self.assertTrue(res.data["access"])

    def test_logout_requires_authentication(self) -> None:
        """
        POST /auth/logout/ requires authentication (IsAuthenticated).
        """
        res = self.client.post(
            self.logout_url,
            data={"refresh": "anything"},
            format="json"
        )

        # Depending on DRF auth setup, unauthenticated can be 401 or 403.
        self.assertIn(
            res.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_logout_returns_400_if_refresh_missing(self) -> None:
        """POST /auth/logout/ without refresh returns 400."""
        tokens = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        res = self.client.post(self.logout_url, data={}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data.get("detail"), "refresh token requis")

    def test_logout_returns_401_if_refresh_invalid(self) -> None:
        """POST /auth/logout/ with invalid refresh returns 401."""
        tokens = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        res = self.client.post(
            self.logout_url,
            data={"refresh": "not-a-real-token"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res.data.get("detail"), "refresh token invalide")

    def test_logout_blacklists_refresh_token_and_refresh_fails_after(self) -> None:
        """
        End-to-end logout behavior:
        - login -> get refresh
        - logout -> blacklist refresh
        - refresh using that same refresh token must fail afterwards
        """
        tokens = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        # 1) Logout blacklists the refresh token
        res_logout = self.client.post(
            self.logout_url,
            data={"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(res_logout.status_code, status.HTTP_205_RESET_CONTENT)

        # 2) That refresh token should no longer be usable
        res_refresh = self.client.post(
            self.refresh_url,
            data={"refresh": tokens["refresh"]},
            format="json",
        )

        # SimpleJWT typically returns 401 "token_not_valid" when blacklisted.
        self.assertIn(
            res_refresh.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
