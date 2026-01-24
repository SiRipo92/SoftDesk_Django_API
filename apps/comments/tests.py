"""
Comments app test suite.

Coverage targets:
- models.py
  - Comment.clean()/save() contributor validation
- serializers.py
  - CommentWriteSerializer.create() context requirements + model error surfacing
  - CommentSummarySerializer / CommentDetailSerializer / CommentAdminListSerializer
- views.py
  - /comments/ list admin-only
  - /comments/{uuid}/ retrieve/update/delete author-or-staff only
  - POST not exposed on /comments/ (405)
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
from rest_framework.test import APITestCase

from apps.issues.models import Issue
from apps.projects.models import Contributor, Project

from .models import Comment
from .serializers import (
    CommentAdminListSerializer,
    CommentDetailSerializer,
    CommentSummarySerializer,
    CommentWriteSerializer,
)

User = get_user_model()

DEFAULT_PASSWORD = "password123"
DEFAULT_BIRTH_DATE = date(1990, 1, 1)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def api_reverse(name: str, kwargs: dict[str, Any] | None = None) -> str:
    """
    Reverse a router name with fallbacks (with/without app namespace).

    Tries:
    - name
    - comments:name
    - hyphenated variant
    - comments:hyphenated variant
    """
    candidates = [
        name,
        f"comments:{name}",
        name.replace("_", "-"),
        f"comments:{name.replace('_', '-')}",
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


def create_project_minimal(*, author: User) -> Project:
    """
    Create a Project with conservative defaults via model introspection.

    Ensures the author also has a Contributor membership row,
    since multiple scopes rely on the through table.
    """
    kwargs: dict[str, Any] = {"author": author}

    for field in Project._meta.fields:
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
            # Only required FK here should be author (already set)
            continue

        if isinstance(field, models.CharField):
            kwargs[field.name] = "Project"
        elif isinstance(field, models.TextField):
            kwargs[field.name] = "Project"
        elif isinstance(field, models.BooleanField):
            kwargs[field.name] = False
        elif isinstance(field, models.IntegerField):
            kwargs[field.name] = 1
        elif isinstance(field, models.DateTimeField):
            kwargs[field.name] = timezone.now()
        elif isinstance(field, models.DateField):
            kwargs[field.name] = timezone.now().date()
        else:
            kwargs[field.name] = "Project"

    project = Project.objects.create(**kwargs)

    Contributor.objects.get_or_create(
        project=project,
        user=author,
        defaults={"added_by": author},
    )
    return project


def add_contributor(*, project: Project, user: User, added_by: User) -> Contributor:
    """Add a Contributor membership row."""
    return Contributor.objects.create(project=project, user=user, added_by=added_by)


def create_issue_minimal(*, project: Project, author: User) -> Issue:
    """
    Create an Issue with conservative defaults via model introspection.

    Ensures issue.author is a project contributor to satisfy Issue validation.
    """
    if not project.contributors.filter(pk=author.pk).exists():
        Contributor.objects.create(
            project=project, user=author, added_by=project.author
        )

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
            issue_kwargs[field.name] = "Issue"
        elif isinstance(field, models.TextField):
            issue_kwargs[field.name] = "Issue"
        elif isinstance(field, models.BooleanField):
            issue_kwargs[field.name] = False
        elif isinstance(field, models.IntegerField):
            issue_kwargs[field.name] = 1
        elif isinstance(field, models.DateTimeField):
            issue_kwargs[field.name] = timezone.now()
        elif isinstance(field, models.DateField):
            issue_kwargs[field.name] = timezone.now().date()
        else:
            issue_kwargs[field.name] = "Issue"

    return Issue.objects.create(**issue_kwargs)


def create_comment(
    *, issue: Issue, author: User, description: str = "Hello"
) -> Comment:
    """
    Create a Comment (requires author to be a project contributor).
    """
    project = issue.project
    if not project.contributors.filter(pk=author.pk).exists():
        Contributor.objects.create(
            project=project, user=author, added_by=project.author
        )

    return Comment.objects.create(issue=issue, author=author, description=description)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class CommentModelTests(APITestCase):
    """Unit tests for Comment model validation rules."""

    def test_comment_save_rejects_author_not_project_contributor(self) -> None:
        owner = create_user(username="owner_m", email="owner_m@example.com")
        outsider = create_user(username="outsider_m", email="outsider_m@example.com")

        project = create_project_minimal(author=owner)
        issue = create_issue_minimal(project=project, author=owner)

        comment = Comment(issue=issue, author=outsider, description="Nope")

        with self.assertRaises(ValidationError) as ctx:
            comment.save()

        self.assertIn("author", ctx.exception.message_dict)

    def test_comment_str_returns_uuid(self) -> None:
        owner = create_user(username="owner_m2", email="owner_m2@example.com")
        project = create_project_minimal(author=owner)
        issue = create_issue_minimal(project=project, author=owner)
        comment = create_comment(issue=issue, author=owner, description="Hi")

        self.assertEqual(str(comment), str(comment.uuid))


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


class CommentSerializerTests(APITestCase):
    """Serializer behavior tests (not view wiring)."""

    def test_comment_write_serializer_requires_issue_in_context(self) -> None:
        actor = create_user(username="actor_s", email="actor_s@example.com")

        req = RequestFactory().post("/fake")
        req.user = actor

        serializer = CommentWriteSerializer(
            data={"description": "Test"},
            context={"request": req},
        )
        serializer.is_valid(raise_exception=True)

        with self.assertRaises(Exception) as ctx:
            serializer.save()

        self.assertIn("issue", str(ctx.exception).lower())

    def test_comment_write_serializer_surfaces_model_validation(self) -> None:
        owner = create_user(username="owner_s", email="owner_s@example.com")
        outsider = create_user(username="outsider_s", email="outsider_s@example.com")

        project = create_project_minimal(author=owner)
        issue = create_issue_minimal(project=project, author=owner)

        req = RequestFactory().post("/fake")
        req.user = outsider  # outsider is NOT contributor

        serializer = CommentWriteSerializer(
            data={"description": "Test"},
            context={"request": req, "issue": issue},
        )
        serializer.is_valid(raise_exception=True)

        with self.assertRaises(Exception) as ctx:
            serializer.save()

        self.assertIn("author", str(ctx.exception).lower())

    def test_comment_summary_serializer_smoke(self) -> None:
        owner = create_user(username="owner_sum", email="owner_sum@example.com")
        project = create_project_minimal(author=owner)
        issue = create_issue_minimal(project=project, author=owner)
        comment = create_comment(issue=issue, author=owner, description="Hi")

        data = CommentSummarySerializer(comment).data
        for key in (
            "uuid",
            "description",
            "author_id",
            "author_username",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, data)

    def test_comment_detail_serializer_smoke(self) -> None:
        owner = create_user(username="owner_det", email="owner_det@example.com")
        project = create_project_minimal(author=owner)
        issue = create_issue_minimal(project=project, author=owner)
        comment = create_comment(issue=issue, author=owner, description="Hi")

        data = CommentDetailSerializer(comment).data
        for key in (
            "uuid",
            "description",
            "issue_id",
            "issue_title",
            "project_id",
            "project_name",
            "author_id",
            "author_username",
            "author_email",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, data)

    def test_comment_admin_list_serializer_smoke(self) -> None:
        owner = create_user(username="owner_admin", email="owner_admin@example.com")
        project = create_project_minimal(author=owner)
        issue = create_issue_minimal(project=project, author=owner)
        comment = create_comment(issue=issue, author=owner, description="Hi")

        data = CommentAdminListSerializer(comment).data
        for key in (
            "uuid",
            "description",
            "project_id",
            "issue_id",
            "author_id",
            "author_username",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, data)


# ---------------------------------------------------------------------------
# Viewset / API tests
# ---------------------------------------------------------------------------


class CommentViewSetTests(APITestCase):
    """Integration tests for /comments/ endpoints and permissions."""

    def setUp(self) -> None:
        self.owner = create_user(username="owner", email="owner@example.com")
        self.other = create_user(username="other", email="other@example.com")
        self.stranger = create_user(username="stranger", email="stranger@example.com")
        self.admin = create_admin(username="admin", email="admin@example.com")

        self.project = create_project_minimal(author=self.owner)
        add_contributor(project=self.project, user=self.other, added_by=self.owner)

        self.issue = create_issue_minimal(project=self.project, author=self.owner)

        self.comment_owner = create_comment(
            issue=self.issue, author=self.owner, description="Owner"
        )
        self.comment_other = create_comment(
            issue=self.issue, author=self.other, description="Other"
        )

        # Another project/comment for admin list coverage
        other_project = create_project_minimal(author=self.other)
        other_issue = create_issue_minimal(project=other_project, author=self.other)
        self.comment_elsewhere = create_comment(
            issue=other_issue, author=self.other, description="Else"
        )

    # -------------------------
    # /comments/ list (admin only)
    # -------------------------

    def test_list_admin_only(self) -> None:
        url = api_reverse("comments:comments-list")

        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        results = extract_results(resp.data)
        ids = {row["uuid"] for row in results}

        self.assertIn(str(self.comment_owner.uuid), ids)
        self.assertIn(str(self.comment_elsewhere.uuid), ids)

        # Admin list serializer contract
        sample = results[0]
        for key in (
            "uuid",
            "description",
            "project_id",
            "issue_id",
            "author_id",
            "author_username",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, sample)

    def test_post_not_exposed_on_comments_root(self) -> None:
        """
        POST /comments/ must not exist
        (creation happens via nested issues endpoint).
        """
        url = api_reverse("comments:comments-list")

        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(url, data={"description": "Nope"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # -------------------------
    # /comments/{uuid}/ retrieve/update/delete
    # -------------------------

    def test_retrieve_allowed_for_author_or_admin(self) -> None:
        url = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(self.comment_owner.uuid)}
        )

        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_retrieve_denied_for_non_author_non_admin(self) -> None:
        url = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(self.comment_owner.uuid)}
        )

        self.client.force_authenticate(user=self.stranger)
        resp = self.client.get(url)

        # With queryset scoping, this is typically 404 (preferred).
        self.assertIn(
            resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        )

    def test_patch_allowed_for_author_or_admin(self) -> None:
        url = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(self.comment_owner.uuid)}
        )

        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(url, data={"description": "Updated"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["description"], "Updated")

        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            url, data={"description": "Admin update"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["description"], "Admin update")

    def test_patch_denied_for_non_author_non_admin(self) -> None:
        url = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(self.comment_owner.uuid)}
        )

        self.client.force_authenticate(user=self.stranger)
        resp = self.client.patch(url, data={"description": "Nope"}, format="json")
        self.assertIn(
            resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        )

    def test_delete_allowed_for_author_or_admin(self) -> None:
        # Author delete
        comment = create_comment(
            issue=self.issue, author=self.owner, description="Del1"
        )
        url = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(comment.uuid)}
        )

        self.client.force_authenticate(user=self.owner)
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        # Admin delete
        comment2 = create_comment(
            issue=self.issue, author=self.other, description="Del2"
        )
        url2 = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(comment2.uuid)}
        )

        self.client.force_authenticate(user=self.admin)
        resp = self.client.delete(url2)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_denied_for_non_author_non_admin(self) -> None:
        url = api_reverse(
            "comments:comments-detail", kwargs={"uuid": str(self.comment_other.uuid)}
        )

        self.client.force_authenticate(user=self.stranger)
        resp = self.client.delete(url)
        self.assertIn(
            resp.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        )
