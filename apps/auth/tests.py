from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()

DEFAULT_BIRTH_DATE = date(1990, 1, 1)


class JwtEndpointsTests(APITestCase):
    """Covers JWT login (pair), refresh, and logout (refresh blacklisting)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.password = "TestPassword!123"
        cls.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password=cls.password,
            birth_date=DEFAULT_BIRTH_DATE,
        )

    def _login_and_get_tokens(self) -> dict:
        """Login via SimpleJWT and return {'access': ..., 'refresh': ...}."""
        url = reverse("auth:login")
        response = self.client.post(
            url,
            {"username": self.user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()

        self.assertIn("access", payload)
        self.assertIn("refresh", payload)

        return payload

    def test_login_success_returns_access_and_refresh(self) -> None:
        tokens = self._login_and_get_tokens()
        self.assertTrue(tokens["access"])
        self.assertTrue(tokens["refresh"])

    def test_login_invalid_credentials_returns_401(self) -> None:
        url = reverse("auth:login")
        response = self.client.post(
            url,
            {"username": self.user.username, "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_success_returns_new_access_token(self) -> None:
        tokens = self._login_and_get_tokens()

        url = reverse("auth:refresh")
        response = self.client.post(
            url,
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()

        self.assertIn("access", payload)
        self.assertTrue(payload["access"])

    def test_logout_requires_authentication(self) -> None:
        """
        With JWT-only authentication classes, unauthenticated requests should 401.
        """
        url = reverse("auth:logout")
        response = self.client.post(
            url,
            {"refresh": "dummy"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token_and_prevents_reuse(self) -> None:
        """
        Logout blacklists the refresh token; refresh should fail afterwards.
        """
        tokens = self._login_and_get_tokens()

        # Authenticate with access token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        logout_url = reverse("auth:logout")
        logout_response = self.client.post(
            logout_url,
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)

        # Try to refresh using blacklisted refresh token -> should fail
        refresh_url = reverse("auth:refresh")
        refresh_response = self.client.post(
            refresh_url,
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertIn(
            refresh_response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED),
        )
