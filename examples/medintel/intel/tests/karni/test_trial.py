# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Trial API: CRUD, access."""

from karni.testing import APITestCase

from intel.viewsets import TrialViewSet


class TrialAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(TrialViewSet, "staff")

    # No assert_isolated: no role's grant on intel.trial:view is 'own' or
    # 'related:<key>', so every role that reads Trial sees every row. If rows belong to
    # someone, declare `class Karni: owner_field` and grant 'own'.
