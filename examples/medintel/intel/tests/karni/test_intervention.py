# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Intervention API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import InterventionViewSet


class InterventionAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(InterventionViewSet, "staff")
