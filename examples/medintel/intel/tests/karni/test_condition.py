# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Condition API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import ConditionViewSet


class ConditionAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(ConditionViewSet, "staff")
