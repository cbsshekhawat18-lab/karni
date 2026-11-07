# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Company API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import CompanyViewSet


class CompanyAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(CompanyViewSet, "staff")

    # No assert_isolated: no role's grant on intel.company:view is 'own' or
    # 'related:<key>', so every role that reads Company sees every row. If rows belong
    # to someone, declare `class Karni: owner_field` and grant 'own'.
