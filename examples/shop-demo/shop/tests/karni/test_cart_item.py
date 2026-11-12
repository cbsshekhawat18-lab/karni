# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The CartItem API: CRUD, access and isolation."""

from karni.testing import APITestCase

from shop.viewsets import CartItemViewSet


class CartItemAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(CartItemViewSet)

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(CartItemViewSet)
