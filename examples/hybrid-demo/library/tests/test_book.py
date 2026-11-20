"""The Book API: CRUD, access and isolation."""

from karni.testing import APITestCase

from library.viewsets import BookViewSet


class BookAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(BookViewSet)

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(BookViewSet)
