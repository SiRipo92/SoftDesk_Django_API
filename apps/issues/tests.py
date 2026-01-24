"""
Issues app test suite.

Coverage targets:
- models.py
  - Issue.clean() / Issue.save() contributor validation
- serializers.py
  - IssueWriteSerializer.create() context rules + model validation surfacing
  - IssueAssigneeAddSerializer validation + create()
  - IssueDetailSerializer structure (smoke)
- views.py (IssueViewSet)
  - list/retrieve scoping (staff vs project contributors)
  - update/delete permissions (author vs contributor vs staff)
  - assignees GET/POST/DELETE permissions + validation + duplicate prevention
  - comments GET + comment_detail permission (minimal coverage; deep tests belong
    to the comments app suite)
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.test import RequestFactory
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.comments.models import Comment
from apps.projects.models import Contributor, Project, ProjectType

from .models import Issue, IssueAssignee, IssueStatus
from .serializers import (
    IssueAssigneeAddSerializer,
    IssueDetailSerializer,
    IssueWriteSerializer,
)

User = get_user_model()

DEFAULT_PASSWORD = "password123"
DEFAULT_BIRTH_DATE = date(1990, 1, 1)


# ---------------------------------------------------------------------------
# URL helpers (works with or without namespace includes)
# ---------------------------------------------------------------------------


def api_reverse(name: str, kwargs: dict[str, Any] | None = None) -> str:
    """
    Reverse a DRF router name with fallbacks.

    Tries:
    - name
    - issues:name
    - hyphenated variant
    - issues:hyphenated variant
    """
    candidates = [
        name,
        f"issues:{name}",
        name.replace("_", "-"),
        f"issues:{name.replace('_', '-')}",
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
    Normalize list responses:
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
    """Create a user for tests (custom User model requires birth_date)."""
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


def create_project(*, author: User, name: str) -> Project:
    """
    Create a project and ensure author has a Contributor membership row.

    This matters because Issue queryset scoping uses:
        Issue.objects.filter(project__contributors=user)
    which depends on the M2M/through table.
    """
    project = Project.objects.create(
        author=author,
        name=name,
        description="",
        project_type=ProjectType.BACK_END,
    )
    Contributor.objects.get_or_create(
        project=project,
        user=author,
        defaults={"added_by": author},
    )
    return project


def add_contributor(*, project: Project, user: User, added_by: User) -> Contributor:
    """Add a Contributor membership row."""
    return Contributor.objects.create(project=project, user=user, added_by=added_by)


def create_issue(*, project: Project, author: User, title: str = "Issue") -> Issue:
    """
    Create an issue while satisfying model validation:
    author must be a project contributor.
    """
    if not project.contributors.filter(pk=author.pk).exists():
        Contributor.objects.create(
            project=project, user=author, added_by=project.author
        )

    issue = Issue.objects.create(
        project=project,
        author=author,
        title=title,
        description="",
        priority="",
        tag="",
    )
    return issue


def create_comment_minimal(*, issue: Issue, author: User) -> Comment:
    """
    Create a Comment instance without hardcoding the comment schema.

    The issues viewset needs:
    - uuid (usually defaulted)
    - issue FK
    - author FK
    - description/text field (commonly "description")

    This helper fills any required non-null non-default fields.
    """
    kwargs: dict[str, Any] = {"issue": issue, "author": author}

    for field in Comment._meta.fields:
        if getattr(field, "primary_key", False):
            continue
        if isinstance(field, (models.AutoField, models.BigAutoField)):
            continue

        if field.name in kwargs:
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

        if field.choices:
            kwargs[field.name] = field.choices[0][0]
            continue

        if isinstance(field, models.ForeignKey):
            rel_model = field.remote_field.model
            if rel_model == User:
                kwargs[field.name] = author
                continue
            if rel_model == Issue:
                kwargs[field.name] = issue
                continue
            raise AssertionError(
                f"create_comment_minimal cannot auto-create required FK '{field.name}' "
                f"to model {rel_model}."
            )

        # Common text fields
        if isinstance(field, models.CharField):
            kwargs[field.name] = "Test"
        elif isinstance(field, models.TextField):
            kwargs[field.name] = "Test"
        elif isinstance(field, models.BooleanField):
            kwargs[field.name] = False
        elif isinstance(field, models.IntegerField):
            kwargs[field.name] = 1
        elif isinstance(field, models.DateTimeField):
            kwargs[field.name] = timezone.now()
        elif isinstance(field, models.DateField):
            kwargs[field.name] = timezone.now().date()
        else:
            kwargs[field.name] = "Test"

    return Comment.objects.create(**kwargs)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class IssueModelTests(APITestCase):
    """Unit tests for Issue model validation rules."""

    def test_issue_save_rejects_author_not_project_contributor(self) -> None:
        owner = create_user(username="owner_m", email="owner_m@example.com")
        stranger = create_user(username="stranger_m", email="stranger_m@example.com")

        project = create_project(author=owner, name="Project M")

        issue = Issue(
            project=project,
            author=stranger,  # not a contributor
            title="Invalid",
            description="",
            priority="",
            tag="",
        )

        with self.assertRaises(ValidationError) as ctx:
            issue.save()

        self.assertIn("author", ctx.exception.message_dict)


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


class IssueSerializerTests(APITestCase):
    """Serializer behavior tests (not view wiring)."""

    def test_issue_write_serializer_requires_project_in_context(self) -> None:
        actor = create_user(username="actor_s", email="actor_s@example.com")

        req = RequestFactory().post("/fake")
        req.user = actor

        serializer = IssueWriteSerializer(
            data={
                "title": "A",
                "description": "",
                "priority": "",
                "tag": "",
                "status": IssueStatus.TODO,
            },
            context={"request": req},
        )
        serializer.is_valid(raise_exception=True)

        with self.assertRaises(Exception) as ctx:
            serializer.save()

        self.assertIn("project", str(ctx.exception).lower())

    def test_issue_write_serializer_surfaces_model_validation(self) -> None:
        owner = create_user(username="owner_s", email="owner_s@example.com")
        stranger = create_user(username="stranger_s", email="stranger_s@example.com")
        project = create_project(author=owner, name="Project S")

        # Stranger is NOT contributor -> Issue.save() raises Django ValidationError
        req = RequestFactory().post("/fake")
        req.user = owner

        serializer = IssueWriteSerializer(
            data={
                "title": "A",
                "description": "",
                "priority": "",
                "tag": "",
                "status": IssueStatus.TODO,
            },
            context={"request": req, "project": project, "author": stranger},
        )
        serializer.is_valid(raise_exception=True)

        with self.assertRaises(Exception) as ctx:
            serializer.save()

        self.assertIn("author", str(ctx.exception).lower())

    def test_issue_assignee_add_serializer_creates_assignment(self) -> None:
        owner = create_user(username="owner_a", email="owner_a@example.com")
        assignee = create_user(username="assignee_a", email="assignee_a@example.com")

        project = create_project(author=owner, name="Project A")
        add_contributor(project=project, user=assignee, added_by=owner)
        issue = create_issue(project=project, author=owner, title="Issue A")

        req = APIRequestFactory().post("/fake")
        req.user = owner

        serializer = IssueAssigneeAddSerializer(
            data={"user": assignee.id},
            context={"request": req, "issue": issue},
        )
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save()

        self.assertEqual(assignment.issue_id, issue.id)
        self.assertEqual(assignment.user_id, assignee.id)
        self.assertEqual(assignment.assigned_by_id, owner.id)

    def test_issue_assignee_add_serializer_blocks_non_contributor(self) -> None:
        owner = create_user(username="owner_b", email="owner_b@example.com")
        outsider = create_user(username="outsider_b", email="outsider_b@example.com")

        project = create_project(author=owner, name="Project B")
        issue = create_issue(project=project, author=owner, title="Issue B")

        req = APIRequestFactory().post("/fake")
        req.user = owner

        serializer = IssueAssigneeAddSerializer(
            data={"user": outsider.id},
            context={"request": req, "issue": issue},
        )
        self.assertFalse(serializer.is_valid())

    def test_issue_assignee_add_serializer_blocks_duplicates(self) -> None:
        owner = create_user(username="owner_c", email="owner_c@example.com")
        assignee = create_user(username="assignee_c", email="assignee_c@example.com")

        project = create_project(author=owner, name="Project C")
        add_contributor(project=project, user=assignee, added_by=owner)
        issue = create_issue(project=project, author=owner, title="Issue C")

        IssueAssignee.objects.create(issue=issue, user=assignee, assigned_by=owner)

        req = APIRequestFactory().post("/fake")
        req.user = owner

        serializer = IssueAssigneeAddSerializer(
            data={"user": assignee.id},
            context={"request": req, "issue": issue},
        )
        self.assertFalse(serializer.is_valid())

    def test_issue_detail_serializer_smoke(self) -> None:
        owner = create_user(username="owner_d", email="owner_d@example.com")
        project = create_project(author=owner, name="Project D")
        issue = create_issue(project=project, author=owner, title="Issue D")

        req = APIRequestFactory().get("/fake")
        req.user = owner

        data = IssueDetailSerializer(issue, context={"request": req}).data
        for key in ("id", "title", "project_id", "author_id", "comments_preview"):
            self.assertIn(key, data)


# ---------------------------------------------------------------------------
# Viewset / API tests
# ---------------------------------------------------------------------------


class IssueViewSetTests(APITestCase):
    """Integration tests for /issues/ endpoints and nested actions."""

    def setUp(self) -> None:
        self.owner = create_user(username="owner", email="owner@example.com")
        self.contrib = create_user(username="contrib", email="contrib@example.com")
        self.stranger = create_user(username="stranger", email="stranger@example.com")
        self.admin = create_admin(username="admin", email="admin@example.com")

        # Project 1: owner + contrib
        self.project_1 = create_project(author=self.owner, name="P1")
        add_contributor(project=self.project_1, user=self.contrib, added_by=self.owner)

        self.issue_owner = create_issue(
            project=self.project_1, author=self.owner, title="I1"
        )
        self.issue_contrib = create_issue(
            project=self.project_1, author=self.contrib, title="I2"
        )

        # Project 2: hidden from owner/contrib
        other_owner = create_user(username="other", email="other@example.com")
        self.project_2 = create_project(author=other_owner, name="P2")
        self.issue_hidden = create_issue(
            project=self.project_2, author=other_owner, title="H1"
        )

    # -------------------------
    # /issues/ list
    # -------------------------

    def test_list_non_staff_only_sees_issues_in_contributor_projects(self) -> None:
        self.client.force_authenticate(user=self.contrib)

        url = api_reverse("issues:issues-list")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in extract_results(resp.data)}

        self.assertIn(self.issue_owner.id, ids)
        self.assertIn(self.issue_contrib.id, ids)
        self.assertNotIn(self.issue_hidden.id, ids)

    def test_list_staff_sees_all_issues(self) -> None:
        self.client.force_authenticate(user=self.admin)

        url = api_reverse("issues:issues-list")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in extract_results(resp.data)}

        self.assertIn(self.issue_owner.id, ids)
        self.assertIn(self.issue_hidden.id, ids)

    # -------------------------
    # /issues/{id}/ retrieve
    # -------------------------

    def test_retrieve_denies_non_contributor_by_queryset_scope(self) -> None:
        self.client.force_authenticate(user=self.contrib)

        url = api_reverse("issues:issues-detail", kwargs={"pk": self.issue_hidden.id})
        resp = self.client.get(url)

        # Queryset filtering generally yields 404 (no leakage).
        self.assertIn(
            resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        )

    # -------------------------
    # update/delete permissions
    # -------------------------

    def test_update_only_issue_author_or_staff(self) -> None:
        url = api_reverse("issues:issues-detail", kwargs={"pk": self.issue_owner.id})

        # Contributor but not issue author -> forbidden
        self.client.force_authenticate(user=self.contrib)
        resp = self.client.patch(url, data={"title": "Nope"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Author -> ok
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(url, data={"title": "Updated"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Staff -> ok
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(url, data={"title": "Updated by admin"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_delete_only_issue_author_or_staff(self) -> None:
        issue = create_issue(
            project=self.project_1, author=self.owner, title="ToDelete"
        )
        url = api_reverse("issues:issues-detail", kwargs={"pk": issue.id})

        self.client.force_authenticate(user=self.contrib)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    # -------------------------
    # /issues/{id}/assignees/ GET/POST
    # -------------------------

    def test_assignees_get_allowed_for_project_contributor(self) -> None:
        IssueAssignee.objects.create(
            issue=self.issue_owner,
            user=self.contrib,
            assigned_by=self.owner,
        )

        self.client.force_authenticate(user=self.contrib)
        url = api_reverse("issues:issues-assignees", kwargs={"pk": self.issue_owner.id})
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = extract_results(resp.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["user_id"], self.contrib.id)

        for key in ("assignment_id", "user_id", "username", "email", "assigned_by_id"):
            self.assertIn(key, results[0])

    def test_assignees_post_only_issue_author_or_staff(self) -> None:
        outsider = create_user(username="outsider", email="outsider@example.com")
        url = api_reverse("issues:issues-assignees", kwargs={"pk": self.issue_owner.id})

        # Non-author contributor -> 403
        self.client.force_authenticate(user=self.contrib)
        resp = self.client.post(url, data={"user": self.contrib.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Author -> ok, but assignee must be project contributor -> 400
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(url, data={"user": outsider.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Add outsider as contributor, then assign -> 201
        add_contributor(project=self.project_1, user=outsider, added_by=self.owner)
        resp = self.client.post(url, data={"user": outsider.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # Staff can also assign
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(url, data={"user": self.contrib.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    # -------------------------
    # /issues/{id}/assignees/{user_id}/ DELETE
    # -------------------------

    def test_remove_assignee_only_issue_author_or_staff(self) -> None:
        IssueAssignee.objects.create(
            issue=self.issue_owner,
            user=self.contrib,
            assigned_by=self.owner,
        )
        url = api_reverse(
            "issues:issues-remove-assignee",
            kwargs={"pk": self.issue_owner.id, "user_id": self.contrib.id},
        )

        self.client.force_authenticate(user=self.contrib)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_remove_assignee_404_if_assignment_missing(self) -> None:
        self.client.force_authenticate(user=self.owner)
        url = api_reverse(
            "issues:issues-remove-assignee",
            kwargs={"pk": self.issue_owner.id, "user_id": self.contrib.id},
        )
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------
    # Minimal coverage for comment routes exposed by IssueViewSet
    # (Deep tests belong in apps/comments/tests.py)
    # -------------------------

    def test_comments_get_allowed_for_contributor(self) -> None:
        create_comment_minimal(issue=self.issue_owner, author=self.contrib)

        self.client.force_authenticate(user=self.contrib)
        url = api_reverse("issues:issues-comments", kwargs={"pk": self.issue_owner.id})
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = extract_results(resp.data)
        self.assertGreaterEqual(len(results), 1)

    def test_comment_detail_patch_only_comment_author_or_staff(self) -> None:
        comment = create_comment_minimal(issue=self.issue_owner, author=self.contrib)

        url = api_reverse(
            "issues:issues-comment-detail",
            kwargs={"pk": self.issue_owner.id, "comment_uuid": str(comment.uuid)},
        )

        # Owner is project contributor but not comment author -> forbidden
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(url, data={"description": "Updated"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Comment author -> ok (200)
        self.client.force_authenticate(user=self.contrib)
        resp = self.client.patch(url, data={"description": "Updated"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Staff -> ok (200)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            url, data={"description": "Updated by staff"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
