"""
Projects app test suite.

Coverage targets:
- models.py: Project.is_contributor()
- serializers.py:
  - ProjectCreateSerializer.create()
  - ContributorCreateSerializer.validate()/create()
  - ProjectDetailSerializer contributor output logic
- views.py:
  - /projects/ list scoping (staff vs non-staff)
  - /projects/{id} retrieve scoping (owner or contributor)
  - write restrictions (owner/staff)
  - contributors endpoints (GET/POST/DELETE)
  - issues endpoints permission smoke tests + issue_detail write restriction
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import models
from django.test import RequestFactory
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.issues.models import Issue

from .models import Contributor, Project, ProjectType
from .serializers import (
    ContributorReadSerializer,
    ContributorWriteSerializer,
    ProjectDetailSerializer,
    ProjectListSerializer,
    ProjectWriteSerializer,
)

User = get_user_model()

DEFAULT_PASSWORD = "password123"
DEFAULT_BIRTH_DATE = date(1990, 1, 1)


# ---------------------------------------------------------------------------
# URL helpers (works with or without a Django include namespace)
# ---------------------------------------------------------------------------


def api_reverse(name: str, kwargs: dict[str, Any] | None = None) -> str:
    """
    Reverse a DRF router name with a fallback if the app is included as namespaced.

    Tries:
    - name
    - projects:name
    - hyphenated variant (DRF actions use hyphens)
    - projects:hyphenated variant
    """
    candidates = [
        name,
        f"projects:{name}",
        name.replace("_", "-"),
        f"projects:{name.replace('_', '-')}",
    ]
    last_exc: Exception | None = None

    for candidate in candidates:
        try:
            return reverse(candidate, kwargs=kwargs)
        except NoReverseMatch as exc:
            last_exc = exc

    raise last_exc  # type: ignore[misc]


def extract_results(payload: Any) -> list[dict[str, Any]]:
    """
    Normalize list responses.

    DRF can return:
    - list (no pagination)
    - dict with "results" (pagination enabled)
    """
    if isinstance(payload, dict) and "results" in payload:
        return list(payload["results"])
    if isinstance(payload, list):
        return list(payload)
    raise AssertionError(f"Unexpected list payload type: {type(payload)!r}")


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def create_user(
    *,
    username: str,
    email: str,
    password: str = DEFAULT_PASSWORD,
    birth_date: date = DEFAULT_BIRTH_DATE,
    **extra_fields: Any,
) -> User:
    """Create a user (custom User model requires birth_date)."""
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
        **extra_fields,
    )


def create_admin(
    *,
    username: str,
    email: str,
    password: str = DEFAULT_PASSWORD,
    birth_date: date = DEFAULT_BIRTH_DATE,
    **extra_fields: Any,
) -> User:
    """Create a staff/superuser."""
    return User.objects.create_superuser(
        username=username,
        email=email,
        password=password,
        birth_date=birth_date,
        **extra_fields,
    )


def create_project(
    *, author: User, name: str, project_type: str = ProjectType.BACK_END
) -> Project:
    """
    Create a project and ensure the author is a contributor in DB.

    This keeps tests stable even if some code paths rely on membership rows
    for visibility/permissions.
    """
    project = Project.objects.create(
        author=author,
        name=name,
        description="",
        project_type=project_type,
    )
    Contributor.objects.get_or_create(
        project=project,
        user=author,
        defaults={"added_by": author},
    )
    return project


def add_contributor(*, project: Project, user: User, added_by: User) -> Contributor:
    """Add a contributor membership row."""
    return Contributor.objects.create(project=project, user=user, added_by=added_by)


def create_issue_minimal(*, project: Project, author: User) -> Issue:
    """
    Create an Issue with conservative defaults by introspecting required fields.

    This avoids hardcoding your Issue schema in this module.
    If you later add a required FK to a different model, update this helper.
    """
    issue_kwargs: dict[str, Any] = {"project": project, "author": author}

    for field in Issue._meta.fields:
        if getattr(field, "primary_key", False):
            continue
        if isinstance(field, (models.AutoField, models.BigAutoField)):
            continue

        if field.name in issue_kwargs:
            continue

        if field.default is not models.NOT_PROVIDED:
            continue

        if isinstance(field, models.DateTimeField) and (
            field.auto_now or field.auto_now_add
        ):
            continue
        if isinstance(field, models.DateField) and (
            field.auto_now or field.auto_now_add
        ):
            continue

        if field.null:
            continue

        if isinstance(field, models.ForeignKey):
            rel_model = field.remote_field.model
            if rel_model == User:
                issue_kwargs[field.name] = author
                continue
            if rel_model == Project:
                issue_kwargs[field.name] = project
                continue
            raise AssertionError(
                f"create_issue_minimal cannot auto-create required FK '{field.name}' "
                f"to model {rel_model}."
            )

        if field.choices:
            issue_kwargs[field.name] = field.choices[0][0]
            continue

        if isinstance(field, models.CharField):
            issue_kwargs[field.name] = "Test"
        elif isinstance(field, models.TextField):
            issue_kwargs[field.name] = "Test"
        elif isinstance(field, models.IntegerField):
            issue_kwargs[field.name] = 1
        elif isinstance(field, models.BooleanField):
            issue_kwargs[field.name] = False
        elif isinstance(field, models.DateTimeField):
            issue_kwargs[field.name] = timezone.now()
        elif isinstance(field, models.DateField):
            issue_kwargs[field.name] = timezone.now().date()
        elif isinstance(field, models.DecimalField):
            issue_kwargs[field.name] = Decimal("1.0")
        else:
            issue_kwargs[field.name] = "Test"

    return Issue.objects.create(**issue_kwargs)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class ProjectModelTests(APITestCase):
    """Unit tests for Project model helpers."""

    def test_is_contributor_true_for_members(self) -> None:
        """Project.is_contributor returns True for the owner and contributor users."""
        owner = create_user(username="owner_m", email="owner_m@example.com")
        other = create_user(username="other_m", email="other_m@example.com")

        project = create_project(author=owner, name="P1")
        add_contributor(project=project, user=other, added_by=owner)

        self.assertTrue(project.is_contributor(owner))
        self.assertTrue(project.is_contributor(other))

    def test_is_contributor_false_for_non_member_or_none(self) -> None:
        """Project.is_contributor returns False for non-members and for None input."""
        owner = create_user(username="owner_m2", email="owner_m2@example.com")
        stranger = create_user(username="stranger_m2", email="stranger_m2@example.com")
        project = create_project(author=owner, name="P2")

        self.assertFalse(project.is_contributor(stranger))
        self.assertFalse(project.is_contributor(None))


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


class ProjectSerializerTests(APITestCase):
    """Tests focused on serializer behavior (not view wiring)."""

    def test_project_write_serializer_creates_membership(self) -> None:
        """
        ProjectWriteSerializer creates a Project and ensures the author
        is a Contributor.
        """
        actor = create_user(username="actor_s", email="actor_s@example.com")

        request = RequestFactory().post("/fake")
        request.user = actor

        serializer = ProjectWriteSerializer(
            data={
                "name": "API",
                "description": "Desc",
                "project_type": ProjectType.BACK_END,
            },
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        project = serializer.save()

        self.assertEqual(project.author_id, actor.id)
        self.assertTrue(
            Contributor.objects.filter(project=project, user=actor).exists()
        )

        membership = Contributor.objects.get(project=project, user=actor)
        self.assertEqual(membership.added_by_id, actor.id)

    def test_contributor_write_serializer_requires_exactly_one_lookup_key(
        self,
    ) -> None:
        """
        ContributorWriteSerializer.validate rejects missing or
        multiple lookup keys.
        """
        owner = create_user(username="owner_s", email="owner_s@example.com")
        project = create_project(author=owner, name="PS")

        request = RequestFactory().post("/fake")
        request.user = owner

        # missing both
        serializer = ContributorWriteSerializer(
            data={},
            context={"request": request, "project": project},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

        # provided both
        serializer = ContributorWriteSerializer(
            data={"username": "x", "email": "x@example.com"},
            context={"request": request, "project": project},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

    def test_project_detail_serializer_hides_owner_from_contributors(self) -> None:
        """
        ProjectDetailSerializer excludes the project owner from
        the contributors output.
        """
        owner = create_user(username="owner_s2", email="owner_s2@example.com")
        project = create_project(author=owner, name="PD")

        req = APIRequestFactory().get("/fake")
        req.user = owner

        data = ProjectDetailSerializer(project, context={"request": req}).data
        self.assertEqual(data.get("contributors", []), [])

    def test_project_list_serializer_smoke(self) -> None:
        """
        ProjectListSerializer exposes expected list fields, including annotated counts.
        """
        owner = create_user(username="owner_list_s", email="owner_list_s@example.com")
        project = create_project(author=owner, name="ListProject")

        # These values are normally added by queryset annotations in the viewset.
        # For a serializer unit test, we simulate them on the instance.
        project.contributors_count = 0  # type: ignore[attr-defined]
        project.issues_count = 0  # type: ignore[attr-defined]

        data = ProjectListSerializer(project).data

        for key in (
            "id",
            "name",
            "project_type",
            "author_id",
            "author_username",
            "contributors_count",
            "issues_count",
        ):
            self.assertIn(key, data)

    def test_contributor_read_serializer_smoke(self) -> None:
        """
        ContributorReadSerializer returns the flattened membership/user/added_by shape.
        """
        owner = create_user(username="owner_cr_s", email="owner_cr_s@example.com")
        other = create_user(username="other_cr_s", email="other_cr_s@example.com")

        project = create_project(author=owner, name="ContributorReadProject")
        membership = add_contributor(project=project, user=other, added_by=owner)

        data = ContributorReadSerializer(membership).data

        for key in (
            "membership_id",
            "user_id",
            "username",
            "email",
            "added_by",
        ):
            self.assertIn(key, data)


# ---------------------------------------------------------------------------
# Viewset / API tests
# ---------------------------------------------------------------------------


class ProjectViewSetTests(APITestCase):
    """Integration tests for ProjectViewSet endpoints and permissions."""

    def setUp(self) -> None:
        """Create users and projects for permission/scoping integration tests."""
        self.owner = create_user(username="owner", email="owner@example.com")
        self.contrib = create_user(username="contrib", email="contrib@example.com")
        self.stranger = create_user(username="stranger", email="stranger@example.com")
        self.admin = create_admin(username="admin", email="admin@example.com")

        self.p_owned = create_project(author=self.owner, name="Owned")
        add_contributor(project=self.p_owned, user=self.contrib, added_by=self.owner)

        other_owner = create_user(username="other", email="other@example.com")
        self.p_contrib = create_project(author=other_owner, name="ContribProject")
        add_contributor(project=self.p_contrib, user=self.owner, added_by=other_owner)

        self.p_hidden = create_project(author=other_owner, name="Hidden")

    # -------------------------
    # /projects/ list/create
    # -------------------------

    def test_list_non_staff_returns_only_owned_projects(self) -> None:
        """Non-staff users only see projects they own in the /projects/ list."""
        self.client.force_authenticate(user=self.owner)

        url = api_reverse("projects-list")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in extract_results(resp.data)}

        self.assertIn(self.p_owned.id, ids)
        self.assertNotIn(self.p_contrib.id, ids)
        self.assertNotIn(self.p_hidden.id, ids)

    def test_list_staff_returns_all_projects(self) -> None:
        """Staff users can list all projects in the /projects/ endpoint."""
        self.client.force_authenticate(user=self.admin)

        url = api_reverse("projects-list")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in extract_results(resp.data)}

        self.assertIn(self.p_owned.id, ids)
        self.assertIn(self.p_contrib.id, ids)
        self.assertIn(self.p_hidden.id, ids)

    def test_create_returns_detail_shape_and_creates_membership(self) -> None:
        """POST /projects/ returns detail payload and creates owner membership."""
        self.client.force_authenticate(user=self.owner)

        url = api_reverse("projects-list")
        payload = {
            "name": "New Project",
            "description": "Desc",
            "project_type": ProjectType.FRONT_END,
        }
        resp = self.client.post(url, data=payload, format="json")

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", resp.data)
        self.assertEqual(resp.data["author_id"], self.owner.id)
        self.assertEqual(resp.data.get("contributors", []), [])

        project_id = resp.data["id"]
        self.assertTrue(
            Contributor.objects.filter(project_id=project_id, user=self.owner).exists()
        )

    # -------------------------
    # /projects/{id}/ retrieve/update/delete
    # -------------------------

    def test_retrieve_owner_or_contributor_allowed(self) -> None:
        """GET /projects/{id}/ is allowed for the owner and contributors."""
        self.client.force_authenticate(user=self.owner)

        url_owned = api_reverse("projects-detail", kwargs={"pk": self.p_owned.id})
        url_contrib = api_reverse("projects-detail", kwargs={"pk": self.p_contrib.id})

        resp = self.client.get(url_owned)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp = self.client.get(url_contrib)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_retrieve_non_member_denied(self) -> None:
        """GET /projects/{id}/ is denied (403/404) for non-members."""
        self.client.force_authenticate(user=self.stranger)

        url = api_reverse("projects-detail", kwargs={"pk": self.p_hidden.id})
        resp = self.client.get(url)

        # Depending on queryset scoping, 404 is acceptable to avoid leaking existence
        self.assertIn(
            resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        )

    def test_update_allowed_for_owner_or_staff_only(self) -> None:
        """
        PATCH /projects/{id}/ is allowed for owner/staff and
        forbidden for contributors.
        """
        url = api_reverse("projects-detail", kwargs={"pk": self.p_owned.id})

        # contributor forbidden
        self.client.force_authenticate(user=self.contrib)
        resp = self.client.patch(url, data={"name": "Nope"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # owner allowed
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(url, data={"name": "Updated"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # staff allowed
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(url, data={"name": "Updated by admin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_allowed_for_owner_or_staff_only(self) -> None:
        """
        DELETE /projects/{id}/ is allowed for owner and
        forbidden for contributors.
        """
        project = create_project(author=self.owner, name="ToDelete")
        add_contributor(project=project, user=self.contrib, added_by=self.owner)
        url = api_reverse("projects-detail", kwargs={"pk": project.id})

        self.client.force_authenticate(user=self.contrib)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    # -------------------------
    # /projects/{id}/contributors/ GET/POST
    # -------------------------

    def test_contributors_get_allowed_for_contributor_and_hides_owner(self) -> None:
        """
        GET /projects/{id}/contributors/ is allowed for members
        and hides the owner.
        """
        self.client.force_authenticate(user=self.contrib)

        url = api_reverse("projects-contributors", kwargs={"pk": self.p_owned.id})
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = extract_results(resp.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["user_id"], self.contrib.id)

        for key in ("membership_id", "user_id", "username", "email", "added_by"):
            self.assertIn(key, results[0])

    def test_contributors_post_allowed_for_owner_or_staff_only(self) -> None:
        """
        POST /projects/{id}/contributors/ is allowed for owner
        and forbidden for contributors.
        """
        newcomer = create_user(username="newc", email="newc@example.com")
        url = api_reverse("projects-contributors", kwargs={"pk": self.p_owned.id})

        self.client.force_authenticate(user=self.contrib)
        resp = self.client.post(
            url, data={"username": newcomer.username}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            url, data={"username": newcomer.username}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Contributor.objects.filter(project=self.p_owned, user=newcomer).exists()
        )

    def test_contributors_post_rejects_both_username_and_email(self) -> None:
        """
        POST /projects/{id}/contributors/ rejects payloads
        providing username and email.
        """
        url = api_reverse("projects-contributors", kwargs={"pk": self.p_owned.id})

        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(
            url, data={"username": "x", "email": "x@example.com"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------
    # /projects/{id}/contributors/{user_id}/ DELETE
    # -------------------------

    def test_remove_contributor_owner_cannot_remove_self(self) -> None:
        """
        Owner cannot remove their own contributor membership
        via DELETE contributor endpoint.
        """
        self.client.force_authenticate(user=self.owner)

        url = api_reverse(
            "projects-remove-contributor",
            kwargs={"pk": self.p_owned.id, "user_id": self.owner.id},
        )
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_contributor_allowed_for_owner_or_staff_only(self) -> None:
        """DELETE contributor is allowed for owner and forbidden for contributors."""
        url = api_reverse(
            "projects-remove-contributor",
            kwargs={"pk": self.p_owned.id, "user_id": self.contrib.id},
        )

        self.client.force_authenticate(user=self.contrib)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(
            Contributor.objects.filter(project=self.p_owned, user=self.contrib).exists()
        )

    # -------------------------
    # /projects/{id}/issues/ + /projects/{id}/issues/{issue_id}/
    # (permission smoke tests)
    # -------------------------

    def test_issues_list_allowed_for_contributor(self) -> None:
        """GET /projects/{id}/issues/ is allowed for project contributors."""
        self.client.force_authenticate(user=self.contrib)

        url = api_reverse("projects-issues", kwargs={"pk": self.p_owned.id})
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_issues_list_denied_for_non_member(self) -> None:
        """GET /projects/{id}/issues/ is denied (403/404) for non-members."""
        self.client.force_authenticate(user=self.stranger)

        url = api_reverse("projects-issues", kwargs={"pk": self.p_owned.id})
        resp = self.client.get(url)

        self.assertIn(
            resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        )

    def test_issues_post_rejects_mismatched_project_in_payload(self) -> None:
        """
        This test only targets the mismatch guard in views.py (runs before serializer).
        """
        other_project = create_project(author=self.owner, name="Other")
        self.client.force_authenticate(user=self.contrib)

        url = api_reverse("projects-issues", kwargs={"pk": self.p_owned.id})
        resp = self.client.post(url, data={"project": other_project.id}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_issue_detail_patch_only_issue_author_or_staff(self) -> None:
        """
        PATCH /projects/{id}/issues/{issue_id}/ is restricted
        to issue author or staff.
        """
        issue = create_issue_minimal(project=self.p_owned, author=self.contrib)

        url = api_reverse(
            "projects-issue-detail",
            kwargs={"pk": self.p_owned.id, "issue_id": issue.id},
        )

        # owner is a project contributor, but not issue author -> forbidden
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(url, data={"title": "Updated"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # staff allowed
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(url, data={"title": "Updated by admin"}, format="json")
        self.assertIn(
            resp.status_code, (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST)
        )
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
