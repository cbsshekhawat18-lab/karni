from karni.api import Access, BaseViewSet, Granted, HasRole, Owned

from tests.testapp.models import Category, Note, Product


class CategoryViewSet(BaseViewSet):
    model = Category
    access = Granted()


class ProductViewSet(BaseViewSet):
    """An analyst reads every product, an owner their own."""

    model = Product
    access = Access(read=Owned("owner") | HasRole("analyst"), write=HasRole("analyst"))


class NoteViewSet(BaseViewSet):
    model = Note
    access = Granted()
