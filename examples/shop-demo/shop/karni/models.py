"""Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.

Your own code goes in shop/models.py, in the subclass of each class here.
"""

from django.conf import settings
from django.db import models
from karni.fields import MoneyField, SearchField, SlugField, StateField
from karni.models import BaseModel


class Category(BaseModel):
    name = models.CharField(max_length=120)
    slug = SlugField(populate_from="name")
    search = SearchField(sources=["name"])

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]
        verbose_name_plural = "categories"

    class Karni:
        import_key = "slug"

    def __str__(self) -> str:
        return self.name


class Product(BaseModel):
    category = models.ForeignKey("Category", on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    slug = SlugField(populate_from="name")
    description = models.TextField(blank=True)
    price = MoneyField(currency="USD")
    stock = models.IntegerField()
    active = models.BooleanField(default=False)
    search = SearchField(sources=["name", "description"])

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["name"]

    class Karni:
        import_key = "slug"

    def __str__(self) -> str:
        return self.name


class Cart(BaseModel):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta(BaseModel.Meta):
        abstract = True

    class Karni:
        owner_field = "customer"


class CartItem(BaseModel):
    cart = models.ForeignKey("Cart", on_delete=models.CASCADE)
    product = models.ForeignKey("Product", on_delete=models.CASCADE)
    quantity = models.IntegerField()

    class Meta(BaseModel.Meta):
        abstract = True

    class Karni:
        owner_field = "cart__customer"


class Order(BaseModel):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = StateField(
        states=["pending", "paid", "cancelled", "shipped", "refunded", "delivered"],
        transitions={
            "pending": ["paid", "cancelled"],
            "paid": ["shipped", "refunded"],
            "shipped": ["delivered"],
            "delivered": ["refunded"],
        },
    )
    total = MoneyField(currency="USD")
    payment = models.ForeignKey(
        "karni_payments.Payment", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["-created_at"]

    class Karni:
        owner_field = "customer"
        audit = ["status"]


class OrderItem(BaseModel):
    order = models.ForeignKey("Order", on_delete=models.PROTECT)
    product = models.ForeignKey("Product", on_delete=models.PROTECT)
    quantity = models.IntegerField()
    unit_price = MoneyField(currency="USD")

    class Meta(BaseModel.Meta):
        abstract = True

    class Karni:
        owner_field = "order__customer"
