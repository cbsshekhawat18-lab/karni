"""The Workspace API: CRUD, access and isolation."""

from karni.testing import APITestCase, user_with_roles

from crm.models import Workspace
from crm.viewsets import WorkspaceViewSet


class WorkspaceAPITests(APITestCase):
    def test_crud(self) -> None:
        # The bodies keep the member in the workspace: an update that left them out
        # would make a workspace they cannot reach, which is refused (E134).
        member = self.user_as("member")
        self.assert_crud(WorkspaceViewSet, "member", payload={"members": [str(member.pk)]})

    def test_the_creator_is_a_member_of_the_workspace(self) -> None:
        member, colleague = self.user_as("member"), user_with_roles("member")
        response = self.client_as("member").post(
            "/api/workspaces/", {"name": "North", "members": [str(colleague.pk)]}, format="json"
        )
        assert response.status_code == 201, response.content
        workspace = Workspace.objects.get(pk=response.json()["id"])
        assert set(workspace.members.all()) == {member, colleague}

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(WorkspaceViewSet, "member")
