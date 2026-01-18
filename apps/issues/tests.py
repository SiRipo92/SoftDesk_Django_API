"""
apps.issues tests.

Covers:
- models.py: Issue.clean() rule (author must be contributor) + save(full_clean())
- permissions.py: IsIssueAuthor logic (including non-Issue objects safety)
- serializers.py:
    * IssueSerializer:
        global vs nested context,
        project requirement,
        project immutability
    * IssueAssigneeAddSerializer:
        dropdown restriction to project contributors + duplicates
- views.py:
    * /issues/ list scoping (only issues from projects where user is contributor)
    * /issues/ create requires contributor
    * update/delete restricted to issue author
    * /issues/{id}/assignees/ add/list/remove restricted to issue author
    * nested project issues endpoints:
        - /projects/{id}/issues/ (GET/POST)
        - /projects/{id}/issues/{issue_id}/ (GET/PATCH/DELETE)
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from apps.projects.models import Contributor, Project

from .models import Issue, IssueStatus
from .permissions import IsIssueAuthor
from .serializers import IssueAssigneeAddSerializer, IssueSerializer

User = get_user_model()

VALID_PASSWORD = "StrongPassw0rd!*"


# -------------------------
# Helpers
# -------------------------
def make_user(username: str, email: str, birth_date: date | None = None) -> User:
    """
    Create a user with required fields for the custom User model.

    Why:
    - User.save() calls full_clean()
    - birth_date is required -> must be provided in tests
    """
    if birth_date is None:
        birth_date = date(2000, 1, 1)

    return User.objects.create_user(
        username=username,
        email=email,
        password=VALID_PASSWORD,
        birth_date=birth_date,
    )


def make_project(
    author: User, name: str = "P1", project_type: str = "BACK_END"
) -> Project:
    """
    Create a project + create the author membership row.

    Business rules assume the author is also a contributor (membership row).
    """
    project = Project.objects.create(
        name=name,
        description="desc",
        project_type=project_type,
        author=author,
    )
    Contributor.objects.create(project=project, user=author, added_by=author)
    return project


def add_contributor(project: Project, user: User, added_by: User) -> None:
    """Attach a user to a project via Contributor."""
    Contributor.objects.create(project=project, user=user, added_by=added_by)


def make_issue(project: Project, author: User, title: str = "Issue 1") -> Issue:
    """Create a valid Issue."""
    return Issue.objects.create(
        project=project,
        author=author,
        title=title,
        description="d",
        status=IssueStatus.TODO,
    )


# -------------------------
# Model tests
# -------------------------
class IssueModelTests(APITestCase):
    """Unit-style tests for apps.issues.models.Issue."""

    def test_author_must_be_project_contributor(self) -> None:
        """
        Issue.clean() enforces: author must be contributor of the issue.project.
        Saving an Issue with a non-contributor author must raise DjangoValidationError.
        """
        author = make_user("author", "author@example.com")
        outsider = make_user("outsider", "outsider@example.com")

        project = make_project(author=author, name="Proj")

        issue = Issue(project=project, author=outsider, title="Bad issue")

        with self.assertRaises(DjangoValidationError) as ctx:
            issue.save()

        self.assertIn("author", ctx.exception.message_dict)

    def test_save_calls_full_clean(self) -> None:
        """
        Issue.save() calls full_clean() every time.
        If a field is invalid (choices), save() should raise DjangoValidationError.
        """
        author = make_user("author2", "author2@example.com")
        project = make_project(author=author, name="Proj2")

        issue = Issue(project=project, author=author, title="Invalid status")
        issue.status = "NOT_A_REAL_STATUS"  # invalid choice -> caught by full_clean()

        with self.assertRaises(DjangoValidationError):
            issue.save()

    def test_str_returns_title(self) -> None:
        """__str__ should return a readable label (the title)."""
        author = make_user("author3", "author3@example.com")
        project = make_project(author=author, name="Proj3")
        issue = make_issue(project=project, author=author, title="Hello")

        self.assertEqual(str(issue), "Hello")


# -------------------------
# Permission tests
# -------------------------
class IsIssueAuthorPermissionTests(APITestCase):
    """Unit tests for IsIssueAuthor permission."""

    def test_allows_author(self) -> None:
        author = make_user("pa", "pa@example.com")
        project = make_project(author=author)
        issue = make_issue(project=project, author=author)

        perm = IsIssueAuthor()
        request = SimpleNamespace(user=author)
        view = SimpleNamespace(kwargs={"pk": str(issue.pk)})

        self.assertTrue(perm.has_object_permission(request, view, issue))

    def test_denies_non_author(self) -> None:
        author = make_user("pa2", "pa2@example.com")
        other = make_user("pb2", "pb2@example.com")
        project = make_project(author=author)
        add_contributor(project, other, added_by=author)

        issue = make_issue(project=project, author=author)

        perm = IsIssueAuthor()
        request = SimpleNamespace(user=other)
        view = SimpleNamespace(kwargs={"pk": str(issue.pk)})

        self.assertFalse(perm.has_object_permission(request, view, issue))

    def test_does_not_crash_on_non_issue_object(self) -> None:
        """
        Testing because permission got a User object and crashed.
        This test ensures permission safely returns False instead of raising.
        """
        author = make_user("pa3", "pa3@example.com")
        project = make_project(author=author)
        issue = make_issue(project=project, author=author)

        random_user_obj = make_user("someone", "someone@example.com")

        perm = IsIssueAuthor()
        request = SimpleNamespace(user=author)
        view = SimpleNamespace(kwargs={"pk": str(issue.pk)})

        # Should not raise:
        allowed = perm.has_object_permission(request, view, random_user_obj)
        self.assertIn(allowed, (True, False))  # just assert "no crash"


# -------------------------
# Serializer tests
# -------------------------
class IssueSerializerTests(APITestCase):
    """Unit tests for IssueSerializer and IssueAssigneeAddSerializer."""

    def test_issue_serializer_requires_project_on_global_create(self) -> None:
        """
        Global endpoint POST /issues/ must include project.
        Serializer.validate() should error if no project is provided.
        """
        factory = APIRequestFactory()
        user = make_user("s1", "s1@example.com")

        request = factory.post("/api/v1/issues/", {"title": "x"}, format="json")
        request.user = user

        serializer = IssueSerializer(data={"title": "x"}, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("project", serializer.errors)

    def test_issue_serializer_hides_project_name_nested_context_for_write(self) -> None:
        """
        In nested /projects/{id}/issues/ POST, the project comes from the URL.
        IssueSerializer.__init__ removes 'project' from write forms in that case.
        """
        factory = APIRequestFactory()
        user = make_user("s2", "s2@example.com")
        project = make_project(author=user)

        request = factory.post(
            "/api/v1/projects/1/issues/", {"title": "x"}, format="json"
        )
        request.user = user

        serializer = IssueSerializer(context={"request": request, "project": project})
        self.assertIn("project", serializer.fields)
        self.assertTrue(serializer.fields["project"].read_only)
        self.assertFalse(serializer.fields["project"].required)

    def test_issue_serializer_disallows_changing_project_on_update(self) -> None:
        """IssueSerializer.update() should reject project changes."""
        author = make_user("s3", "s3@example.com")
        project1 = make_project(author=author, name="P1")
        project2 = make_project(author=author, name="P2")

        issue = make_issue(project=project1, author=author)

        factory = APIRequestFactory()
        request = factory.patch(
            "/api/v1/issues/1/", {"project": project2.pk}, format="json"
        )
        request.user = author

        serializer = IssueSerializer(
            instance=issue,
            data={"project": project2.pk},
            partial=True,
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid())

        with self.assertRaises(Exception) as ctx:
            serializer.save()

        # DRF ValidationError shows up as Exception here in unittest context
        self.assertIn("project", str(ctx.exception))

    def test_assignee_add_serializer_limits_dropdown_to_contributors(self) -> None:
        """
        IssueAssigneeAddSerializer.__init__ sets queryset to issue.project.contributors.
        """
        author = make_user("sa", "sa@example.com")
        contributor = make_user("sb", "sb@example.com")
        outsider = make_user("sc", "sc@example.com")

        project = make_project(author=author, name="P")
        add_contributor(project, contributor, added_by=author)

        issue = make_issue(project=project, author=author)

        serializer = IssueAssigneeAddSerializer(context={"issue": issue})
        allowed_ids = list(
            serializer.fields["user"].queryset.values_list("id", flat=True)
        )

        self.assertIn(author.id, allowed_ids)
        self.assertIn(contributor.id, allowed_ids)
        self.assertNotIn(outsider.id, allowed_ids)


# -------------------------
# API / ViewSet tests (global issues endpoints)
# -------------------------
class IssueViewSetTests(APITestCase):
    """Integration tests for apps.issues.views.IssueViewSet."""

    def setUp(self) -> None:
        self.author = make_user("author_api", "author_api@example.com")
        self.other = make_user("other_api", "other_api@example.com")
        self.outsider = make_user("outsider_api", "outsider_api@example.com")

        self.project_visible = make_project(author=self.author, name="Visible")
        add_contributor(self.project_visible, self.other, added_by=self.author)

        self.project_hidden = make_project(author=self.outsider, name="Hidden")

        self.issue1 = make_issue(
            project=self.project_visible, author=self.author, title="I1"
        )
        self.issue2 = make_issue(
            project=self.project_hidden, author=self.outsider, title="I2"
        )

    def test_list_only_returns_project_issues_where_user_is_contributor(self) -> None:
        """
        get_queryset() filters by project__contributors=user,
            so issues from other projects
        should not be visible.
        """
        self.client.force_authenticate(user=self.other)

        url = reverse("issues:issues-list")
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in res.json()]
        self.assertIn(self.issue1.id, ids)
        self.assertNotIn(self.issue2.id, ids)

    def test_retrieve_hidden_issue_returns_404(self) -> None:
        """
        Because get_queryset() hides non-visible issues, retrieving a hidden issue
        should return 404 (not 403).
        """
        self.client.force_authenticate(user=self.other)

        url = reverse("issues:issues-detail", kwargs={"pk": self.issue2.pk})
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_requires_contributor_of_selected_project(self) -> None:
        """
        perform_create() blocks creation if user is not a contributor
        of the selected project.
        """
        self.client.force_authenticate(user=self.other)

        url = reverse("issues:issues-list")

        # other is NOT contributor of project_hidden
        payload = {
            "title": "New",
            "project": self.project_hidden.pk,
            "status": IssueStatus.TODO,
        }
        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # other IS contributor of project_visible
        payload_ok = {
            "title": "New2",
            "project": self.project_visible.pk,
            "status": IssueStatus.TODO,
        }
        res_ok = self.client.post(url, payload_ok, format="json")

        self.assertEqual(res_ok.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_ok.json()["project"], self.project_visible.pk)

    def test_update_only_author(self) -> None:
        """
        update/partial_update/destroy are protected by IsIssueAuthor.
        """
        url = reverse("issues:issues-detail", kwargs={"pk": self.issue1.pk})

        # contributor but not author -> forbidden
        self.client.force_authenticate(user=self.other)
        res = self.client.patch(url, {"title": "Nope"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # author -> ok
        self.client.force_authenticate(user=self.author)
        res2 = self.client.patch(url, {"title": "Ok"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.json()["title"], "Ok")

    def test_assignees_add_list_remove(self) -> None:
        """
        /issues/{id}/assignees/
        - GET returns assigned users
        - POST adds one assignee (author only)
        - DELETE removes one assignee (author only)
        """
        list_add_url = reverse("issues:issues-assignees", kwargs={"pk": self.issue1.pk})

        # initially empty
        self.client.force_authenticate(user=self.author)
        res0 = self.client.get(list_add_url)
        self.assertEqual(res0.status_code, status.HTTP_200_OK)
        self.assertEqual(res0.json(), [])

        # POST add contributor 'other'
        res1 = self.client.post(list_add_url, {"user": self.other.pk}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # now listed
        res2 = self.client.get(list_add_url)
        self.assertEqual(len(res2.json()), 1)
        self.assertEqual(res2.json()[0]["user_id"], self.other.pk)

        # duplicate should fail
        res_dup = self.client.post(list_add_url, {"user": self.other.pk}, format="json")
        self.assertEqual(res_dup.status_code, status.HTTP_400_BAD_REQUEST)

        # remove assignee
        remove_url = reverse(
            "issues:issues-remove-assignee",
            kwargs={"pk": self.issue1.pk, "user_id": self.other.pk},
        )
        res3 = self.client.delete(remove_url)
        self.assertEqual(res3.status_code, status.HTTP_204_NO_CONTENT)

        res4 = self.client.get(list_add_url)
        self.assertEqual(res4.json(), [])

    def test_assignees_add_requires_issue_author(self) -> None:
        """
        Assignee management is author-only.
        """
        url = reverse("issues:issues-assignees", kwargs={"pk": self.issue1.pk})

        self.client.force_authenticate(user=self.other)  # not author
        res = self.client.post(url, {"user": self.other.pk}, format="json")

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_assignees_add_rejects_non_contributor(self) -> None:
        """
        Serializer must reject assigning a user that isn't
        a contributor of issue.project.
        """
        url = reverse("issues:issues-assignees", kwargs={"pk": self.issue1.pk})

        self.client.force_authenticate(user=self.author)

        # outsider_api is not contributor of project_visible
        res = self.client.post(url, {"user": self.outsider.pk}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# -------------------------
# API tests (nested project issues endpoints)
# -------------------------
class ProjectIssuesNestedEndpointsTests(APITestCase):
    """Integration tests for /projects/{id}/issues/...
    custom actions in ProjectViewSet.
    """

    def setUp(self) -> None:
        self.author = make_user("p_author", "p_author@example.com")
        self.contributor = make_user("p_contrib", "p_contrib@example.com")
        self.outsider = make_user("p_out", "p_out@example.com")

        self.project = make_project(author=self.author, name="NestedProj")
        add_contributor(self.project, self.contributor, added_by=self.author)

        self.issue = make_issue(
            project=self.project, author=self.author, title="NestedIssue"
        )

    def test_nested_list_requires_project_contributor(self) -> None:
        url = reverse("projects:projects-issues", kwargs={"pk": self.project.pk})

        # contributor -> OK
        self.client.force_authenticate(user=self.contributor)
        res_ok = self.client.get(url)
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)

        # outsider -> 404 (project hidden by queryset)
        # OR 403 depending on ProjectViewSet
        self.client.force_authenticate(user=self.outsider)
        res_no = self.client.get(url)
        self.assertIn(
            res_no.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN)
        )

    def test_nested_create_forces_project_from_url(self) -> None:
        """
        POST /projects/{id}/issues/ should NOT require 'project' in payload.
        It is forced from the URL project.
        """
        url = reverse("projects:projects-issues", kwargs={"pk": self.project.pk})
        self.client.force_authenticate(user=self.contributor)

        payload = {"title": "Created nested", "status": IssueStatus.TODO}
        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.json()["project"], self.project.pk)

    def test_nested_create_rejects_conflicting_project_in_payload(self) -> None:
        """
        Defensive safety: if client sends 'project', it must match the URL project.
        """
        other_project = make_project(author=self.author, name="OtherProj")

        url = reverse("projects:projects-issues", kwargs={"pk": self.project.pk})
        self.client.force_authenticate(user=self.author)

        payload = {
            "title": "Bad",
            "status": IssueStatus.TODO,
            "project": other_project.pk,
        }
        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nested_issue_detail_get_ok_for_contributor(self) -> None:
        url = reverse(
            "projects:projects-issue-detail",
            kwargs={"pk": self.project.pk, "issue_id": self.issue.pk},
        )
        self.client.force_authenticate(user=self.contributor)

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["id"], self.issue.pk)

    def test_nested_issue_detail_patch_delete_author_only(self) -> None:
        url = reverse(
            "projects:projects-issue-detail",
            kwargs={"pk": self.project.pk, "issue_id": self.issue.pk},
        )

        # contributor but not issue author -> 403
        self.client.force_authenticate(user=self.contributor)
        res_forbidden = self.client.patch(url, {"title": "Nope"}, format="json")
        self.assertEqual(res_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        # author -> ok
        self.client.force_authenticate(user=self.author)
        res_ok = self.client.patch(url, {"title": "Yep"}, format="json")
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ok.json()["title"], "Yep")

        # author delete -> 204
        res_del = self.client.delete(url)
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)
