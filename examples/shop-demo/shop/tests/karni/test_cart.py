# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Cart API: CRUD, access and isolation."""

from karni.testing import APITestCase

from shop.viewsets import CartViewSet


class CartAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(CartViewSet)

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(CartViewSet)
