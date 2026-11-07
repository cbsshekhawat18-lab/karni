from karni.api import Access, BaseViewSet, HasRole, Owned, Public

from tests.testapp.models import Category, Product


class CategoryViewSet(BaseViewSet):
    model = Category
    access = Access(read=Public(), write=HasRole("staff"))


class ProductViewSet(BaseViewSet):
    model = Product
    access = Access(read=Owned("owner") | HasRole("staff"), write=Owned("owner"))
