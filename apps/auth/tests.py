"""
apps/auth/tests.py

Test suite for JWT auth endpoints:
- POST /login/   (TokenObtainPairView)
- POST /refresh/ (TokenRefreshView)
- POST /logout/  (custom LogoutView: blacklists refresh token)

Assumptions:
- Your auth urls are included with namespace "auth" (app_name = "auth")
- SimpleJWT is installed and configured
- LogoutView requires authentication (IsAuthenticated)
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


DEFAULT_BIRTH_DATE = date(1990, 1, 1)


class AuthEndpointsTests(APITestCase):
    """Covers login/refresh/logout behaviors for the apps.auth app."""

    @classmethod
    def setUpTestData(cls) -> None:
        """
        Create a test user once for the whole test class.

        Note:
        - If your custom User model uses email as USERNAME_FIELD, keep the
          create_user call compatible with your model.
        """
        cls.password = "TestPassword!123"
        cls.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password=cls.password,
            birth_date=DEFAULT_BIRTH_DATE,
        )

    def _login_and_get_tokens(self) -> dict:
        """
        Perform login and return token payload.

        Returns:
            dict: {"refresh": "...", "access": "..."} on success.
        """
        url = reverse("auth:login")
        response = self.client.post(
            url,
            {"username": self.user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        return response.data

    def _auth_with_access_token(self, access_token: str) -> None:
        """Attach Bearer access token to subsequent client requests."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

    def test_login_success_returns_access_and_refresh(self) -> None:
        """Login should return both access and refresh tokens."""
        tokens = self._login_and_get_tokens()
        self.assertTrue(tokens["access"])
        self.assertTrue(tokens["refresh"])

    def test_login_invalid_credentials_returns_401(self) -> None:
        """Login with wrong password should fail."""
        url = reverse("auth:login")
        response = self.client.post(
            url,
            {"username": self.user.username, "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_success_returns_new_access(self) -> None:
        """Refresh endpoint should accept a valid refresh token and return access."""
        tokens = self._login_and_get_tokens()

        url = reverse("auth:refresh")
        response = self.client.post(url, {"refresh": tokens["refresh"]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertTrue(response.data["access"])

    def test_logout_requires_authentication(self) -> None:
        """Logout endpoint is protected by IsAuthenticated -> 401 if no access token."""
        url = reverse("auth:logout")
        response = self.client.post(url, {"refresh": "any"}, format="json")
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_logout_missing_refresh_returns_400(self) -> None:
        """
        Missing refresh should be a serializer validation error.

        Note:
        - Your view uses serializer.is_valid(raise_exception=True), so DRF returns
          400 with field error details.
        """
        tokens = self._login_and_get_tokens()
        self._auth_with_access_token(tokens["access"])

        url = reverse("auth:logout")
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("refresh", response.data)

    def test_logout_invalid_refresh_returns_401(self) -> None:
        """Invalid refresh token string should trigger TokenError -> 401 with detail."""
        tokens = self._login_and_get_tokens()
        self._auth_with_access_token(tokens["access"])

        url = reverse("auth:logout")
        response = self.client.post(
            url, {"refresh": "not-a-valid-token"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get("detail"), "refresh token invalide")

    def test_logout_blacklists_refresh_and_prevents_reuse(self) -> None:
        """
        Valid logout should:
        - return 205
        - blacklist the refresh token
        - make refresh endpoint reject it afterwards

        If token_blacklist is not installed, blacklist() won't be available/usable.
        We skip this test to avoid false failures.
        """
        if "rest_framework_simplejwt.token_blacklist" not in settings.INSTALLED_APPS:
            self.skipTest(
                "SimpleJWT token_blacklist app not installed; cannot test blacklisting."
            )

        tokens = self._login_and_get_tokens()
        self._auth_with_access_token(tokens["access"])

        logout_url = reverse("auth:logout")
        logout_response = self.client.post(
            logout_url, {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(logout_response.status_code, status.HTTP_205_RESET_CONTENT)

        # Try to reuse the same refresh token: should now fail
        refresh_url = reverse("auth:refresh")
        refresh_response = self.client.post(
            refresh_url, {"refresh": tokens["refresh"]}, format="json"
        )

        # SimpleJWT typically returns 401 when token is blacklisted / invalid.
        self.assertIn(
            refresh_response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_400_BAD_REQUEST),
        )
