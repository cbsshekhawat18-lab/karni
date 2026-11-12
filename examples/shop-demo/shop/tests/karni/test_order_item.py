# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The OrderItem API: CRUD, access and isolation."""

from karni.testing import APITestCase

from shop.viewsets import OrderItemViewSet


class OrderItemAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(OrderItemViewSet, "staff")

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(OrderItemViewSet)
