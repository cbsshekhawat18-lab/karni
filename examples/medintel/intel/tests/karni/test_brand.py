# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Brand API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import BrandViewSet


class BrandAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(BrandViewSet, "staff")

    # No assert_isolated: no role's grant on intel.brand:view is 'own' or
    # 'related:<key>', so every role that reads Brand sees every row. If rows belong to
    # someone, declare `class Karni: owner_field` and grant 'own'.
