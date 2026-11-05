# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Person API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import PersonViewSet


class PersonAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(PersonViewSet, "staff")

    # No assert_isolated: no role's grant on intel.person:view is 'own' or
    # 'related:<key>', so every role that reads Person sees every row. If rows belong to
    # someone, declare `class Karni: owner_field` and grant 'own'.
