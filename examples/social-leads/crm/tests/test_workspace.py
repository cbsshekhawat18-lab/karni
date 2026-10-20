"""The Workspace API: CRUD, access and isolation."""

from karni.testing import APITestCase

from crm.viewsets import WorkspaceViewSet


class WorkspaceAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(WorkspaceViewSet, "member")

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(WorkspaceViewSet, "member")
