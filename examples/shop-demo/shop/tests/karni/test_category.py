# Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
"""The Category API: CRUD, access."""

from karni.testing import APITestCase

from shop.viewsets import CategoryViewSet


class CategoryAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(CategoryViewSet, "staff")
