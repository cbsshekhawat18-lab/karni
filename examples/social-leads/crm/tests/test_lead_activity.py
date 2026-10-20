"""The LeadActivity API: CRUD, access and isolation."""

from karni.testing import APITestCase

from crm.viewsets import LeadActivityViewSet


class LeadActivityAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(LeadActivityViewSet, "member")

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(LeadActivityViewSet, "member")
