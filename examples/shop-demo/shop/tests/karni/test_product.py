# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Product API: CRUD, access."""

from karni.testing import APITestCase

from shop.viewsets import ProductViewSet


class ProductAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(ProductViewSet, "staff")
