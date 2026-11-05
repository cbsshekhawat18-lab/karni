from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole

from tests.testapp.models import Category, Product, Region, Supplier, Tag


class CategoryViewSet(BaseViewSet):
    model = Category
    access = Granted()


class TagViewSet(BaseViewSet):
    model = Tag
    access = Granted()


class SupplierViewSet(BaseViewSet):
    model = Supplier
    access = Granted()


class ProductViewSet(BaseViewSet):
    """Anyone signed in reads products. Only an editor creates and changes them."""

    model = Product
    access = Access(read=Authenticated(), write=HasRole("editor"))


class RegionViewSet(BaseViewSet):
    model = Region
    access = Granted()
    import_data = False
