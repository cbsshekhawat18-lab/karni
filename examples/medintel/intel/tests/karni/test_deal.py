# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Deal API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import DealViewSet


class DealAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(DealViewSet, "staff")

    # No assert_isolated: no role's grant on intel.deal:view is 'own' or
    # 'related:<key>', so every role that reads Deal sees every row. If rows belong to
    # someone, declare `class Karni: owner_field` and grant 'own'.
