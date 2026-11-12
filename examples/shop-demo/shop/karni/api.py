"""Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.

Your own code goes in shop/viewsets.py, in the subclass of each class here.
"""

from karni.api import Access, BaseViewSet, HasRole, Owned, Public

from shop.models import Cart, CartItem, Category, Order, OrderItem, Product


class CategoryViewSet(BaseViewSet):
    model = Category
    access = Access(read=Public(), write=HasRole("staff"))
    search_fields = ("name",)


class ProductViewSet(BaseViewSet):
    model = Product
    access = Access(read=Public(), write=HasRole("staff"))
    search_fields = ("name", "description")


class CartViewSet(BaseViewSet):
    model = Cart
    access = Access(read=Owned("customer"), write=Owned("customer"))


class CartItemViewSet(BaseViewSet):
    model = CartItem
    access = Access(read=Owned("cart__customer"), write=Owned("cart__customer"))


class OrderViewSet(BaseViewSet):
    model = Order
    access = Access(read=Owned("customer") | HasRole("staff"), write=HasRole("staff"))


class OrderItemViewSet(BaseViewSet):
    model = OrderItem
    access = Access(
        read=Owned("order__customer") | HasRole("staff"), write=HasRole("staff")
    )
