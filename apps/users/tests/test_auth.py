from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _adult_birth_date() -> str:
    """Return a clearly-valid adult birth date (>= 15 years old), ISO format."""
    return (date.today() - timedelta(days=20 * 365)).isoformat()


def _underage_birth_date() -> str:
    """Return a clearly-invalid underage birth date (< 15 years old), ISO format."""
    return (date.today() - timedelta(days=10 * 365)).isoformat()


def _future_birth_date() -> str:
    """Return an invalid future birth date, ISO format."""
    return (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture
def client() -> APIClient:
    """Provide a DRF APIClient instance."""
    return APIClient()


def _auth_header(access_token: str) -> dict[str, str]:
    """
    Build Bearer auth header for APIClient.

    Args:
        access_token (str): JWT access token.

    Returns:
        dict[str, str]: kwargs to pass to APIClient requests.
    """
    return {"HTTP_AUTHORIZATION": f"Bearer {access_token}"}


def test_model_hard_lock_refuses_underage_user_creation() -> None:
    """
    Model-level lock: creating an underage user must raise ValidationError
    even outside the API layer.
    """
    User = get_user_model()
    with pytest.raises(ValidationError):
        User.objects.create_user(
            username="underage_model",
            email="underage_model@example.com",
            password="StrongPass123!",
            birth_date=date.today() - timedelta(days=10 * 365),
        )


def test_signup_success_age_ok_persists_user_and_consents(client: APIClient) -> None:
    """Signup succeeds for a user aged >= 15 and persists consent fields."""
    url = reverse("users:signup")
    payload = {
        "username": "user1",
        "email": "user1@example.com",
        "password": "StrongPass123!",
        "birth_date": _adult_birth_date(),
        "can_be_contacted": True,
        "can_data_be_shared": False,
    }

    res = client.post(url, payload, format="json")
    assert res.status_code == 201
    assert "password" not in res.data

    User = get_user_model()
    user = User.objects.get(username="user1")
    assert user.email == "user1@example.com"
    assert user.can_be_contacted is True
    assert user.can_data_be_shared is False


def test_signup_refused_if_under_15(client: APIClient) -> None:
    """Signup is refused when age < 15 (birth_date validator)."""
    url = reverse("users:signup")
    payload = {
        "username": "teen",
        "email": "teen@example.com",
        "password": "StrongPass123!",
        "birth_date": _underage_birth_date(),
        "can_be_contacted": True,
        "can_data_be_shared": True,
    }

    res = client.post(url, payload, format="json")
    assert res.status_code == 400

    User = get_user_model()
    assert not User.objects.filter(username="teen").exists()


def test_signup_refused_if_birth_date_missing(client: APIClient) -> None:
    """Signup is refused when birth_date is missing (required by serializer)."""
    url = reverse("users:signup")
    payload = {
        "username": "nobirth",
        "email": "nobirth@example.com",
        "password": "StrongPass123!",
        "can_be_contacted": True,
        "can_data_be_shared": False,
    }

    res = client.post(url, payload, format="json")
    assert res.status_code == 400


def test_signup_refused_if_birth_date_in_future(client: APIClient) -> None:
    """Signup is refused when birth_date is in the future."""
    url = reverse("users:signup")
    payload = {
        "username": "future",
        "email": "future@example.com",
        "password": "StrongPass123!",
        "birth_date": _future_birth_date(),
        "can_be_contacted": False,
        "can_data_be_shared": False,
    }

    res = client.post(url, payload, format="json")
    assert res.status_code == 400


def test_login_returns_access_and_refresh(client: APIClient) -> None:
    """Login returns both access and refresh tokens for valid credentials."""
    User = get_user_model()
    user = User.objects.create_user(
        username="user2",
        email="user2@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    url = reverse("users:login")
    res = client.post(url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")

    assert res.status_code == 200
    assert "access" in res.data
    assert "refresh" in res.data


def test_login_refused_with_wrong_password(client: APIClient) -> None:
    """Login is refused (401) for invalid credentials."""
    User = get_user_model()
    user = User.objects.create_user(
        username="user2b",
        email="user2b@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    url = reverse("users:login")
    res = client.post(url, {
        "username": user.username,
        "password": "WrongPassword!"
    }, format="json")

    assert res.status_code == 401


def test_me_requires_authentication(client: APIClient) -> None:
    """/users/me/ requires a valid JWT Bearer token."""
    url = reverse("users:me")
    res = client.get(url)
    assert res.status_code == 401


def test_me_returns_profile_when_authenticated(client: APIClient) -> None:
    """/users/me/ returns the authenticated user's profile (200)."""
    User = get_user_model()
    user = User.objects.create_user(
        username="user3",
        email="user3@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    login_url = reverse("users:login")
    login = client.post(login_url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")
    access = login.data["access"]

    me_url = reverse("users:me")
    res = client.get(me_url, **_auth_header(access))
    assert res.status_code == 200
    assert res.data["username"] == "user3"
    assert "birth_date" in res.data


def test_me_patch_refuses_null_birth_date(client: APIClient) -> None:
    """
    PATCH must refuse birth_date=null (field is not nullable).
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="user_patch_null",
        email="user_patch_null@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    login_url = reverse("users:login")
    login = client.post(login_url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")
    access = login.data["access"]

    me_url = reverse("users:me")
    res = client.patch(me_url, {
        "birth_date": None
    }, format="json", **_auth_header(access))
    assert res.status_code == 400


def test_me_patch_refuses_under_15_birth_date(client: APIClient) -> None:
    """Updating birth_date to an under-15 value is refused (400)."""
    User = get_user_model()
    user = User.objects.create_user(
        username="user_patch",
        email="user_patch@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    login_url = reverse("users:login")
    login = client.post(login_url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")
    access = login.data["access"]

    me_url = reverse("users:me")
    res = client.patch(me_url, {
        "birth_date": _underage_birth_date()
    }, format="json", **_auth_header(access))
    assert res.status_code == 400


def test_refresh_returns_new_access_token(client: APIClient) -> None:
    """Refresh returns a new access token when refresh token is valid."""
    User = get_user_model()
    user = User.objects.create_user(
        username="user_refresh",
        email="user_refresh@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    login_url = reverse("users:login")
    login = client.post(login_url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")
    refresh = login.data["refresh"]

    refresh_url = reverse("users:refresh")
    res = client.post(refresh_url, {"refresh": refresh}, format="json")
    assert res.status_code == 200
    assert "access" in res.data


def test_refresh_refused_if_refresh_invalid(client: APIClient) -> None:
    """Refresh refuses invalid refresh token (401)."""
    refresh_url = reverse("users:refresh")
    res = client.post(refresh_url, {"refresh": "not-a-token"}, format="json")
    assert res.status_code == 401


def test_logout_requires_refresh_token_in_body(client: APIClient) -> None:
    """Logout requires 'refresh' in request body (400 if missing)."""
    User = get_user_model()
    user = User.objects.create_user(
        username="user_logout",
        email="user_logout@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    login_url = reverse("users:login")
    login = client.post(login_url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")
    access = login.data["access"]

    logout_url = reverse("users:logout")
    res = client.post(logout_url, {}, format="json", **_auth_header(access))
    assert res.status_code == 400


def test_logout_blacklists_refresh_token_when_enabled(client: APIClient) -> None:
    """
    Logout blacklists refresh token.

    After logout, using the same refresh token fails.
    """
    User = get_user_model()
    user = User.objects.create_user(
        username="user_logout2",
        email="user_logout2@example.com",
        password="StrongPass123!",
        birth_date=date.today() - timedelta(days=20 * 365),
    )

    login_url = reverse("users:login")
    login = client.post(login_url, {
        "username": user.username,
        "password": "StrongPass123!"
    }, format="json")
    access = login.data["access"]
    refresh = login.data["refresh"]

    logout_url = reverse("users:logout")
    logout = client.post(logout_url, {
        "refresh": refresh
    }, format="json", **_auth_header(access))
    assert logout.status_code == 205

    refresh_url = reverse("users:refresh")
    res = client.post(refresh_url, {
        "refresh": refresh
    }, format="json")
    assert res.status_code == 401
