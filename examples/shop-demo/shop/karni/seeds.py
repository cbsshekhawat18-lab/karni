"""Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.

The rows karni seed makes. Steer a field's values in shop/seeds.py.
"""

from karni.seeding import Seeder

from shop.models import Cart, CartItem, Category, Order, OrderItem, Product


class CategorySeeder(Seeder):
    class Meta:
        model = Category
        count = 5


class ProductSeeder(Seeder):
    class Meta:
        model = Product
        count = 40


class CartSeeder(Seeder):
    class Meta:
        model = Cart
        count = 10


class CartItemSeeder(Seeder):
    class Meta:
        model = CartItem
        count = 30


class OrderSeeder(Seeder):
    class Meta:
        model = Order
        count = 30


class OrderItemSeeder(Seeder):
    class Meta:
        model = OrderItem
        count = 80
