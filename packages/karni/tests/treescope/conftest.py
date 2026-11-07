"""The tree-scope suite's world: two trees, products and listings on them, and the roles."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from tests.testapp.models import Category, Listing, Product, Region
from tests.treescope import ROLES


@pytest.fixture(autouse=True)
def _world(settings: Any, db: Any) -> Iterator[None]:
    settings.KARNI_USER_GRANTS = True
    with override_settings(
        KARNI_ROLES=ROLES,
        ROOT_URLCONF="tests.treescope",
        KARNI_API_ROUTER="tests.treescope.get_router",
    ):
        sync_roles()
        yield


@dataclass
class Catalog:
    """Categories: Everything > (Food > (Fruit > Apples, Dairy), Tools > Saws), and Books.

    Regions: World > Europe > France > Lyon, and Asia > Japan > Tokyo. Each
    product sits in one category and some regions, each listing on one product.
    """

    everything: Category
    food: Category
    fruit: Category
    apples: Category
    dairy: Category
    tools: Category
    saws: Category
    books: Category
    world: Region
    europe: Region
    france: Region
    lyon: Region
    asia: Region
    japan: Region
    tokyo: Region
    pie: Product
    milk: Product
    saw: Product
    novel: Product
    loose: Product

    def ids(self, *nodes: Any) -> list[str]:
        return [str(node.pk) for node in nodes]


def _category(name: str, parent: Category | None = None) -> Category:
    return Category.objects.create(name=name, parent=parent)


def _region(name: str, parent: Region | None = None) -> Region:
    return Region.objects.create(name=name, parent=parent)


@pytest.fixture
def catalog() -> Catalog:
    everything = _category("Everything")
    food = _category("Food", everything)
    fruit = _category("Fruit", food)
    apples = _category("Apples", fruit)
    dairy = _category("Dairy", food)
    tools = _category("Tools", everything)
    saws = _category("Saws", tools)
    books = _category("Books")
    world = _region("World")
    europe = _region("Europe", world)
    france = _region("France", europe)
    lyon = _region("Lyon", france)
    asia = _region("Asia")
    japan = _region("Japan", asia)
    tokyo = _region("Tokyo", japan)
    pie = Product.objects.create(name="Apple pie", category=apples)
    pie.regions.set([lyon, tokyo])
    milk = Product.objects.create(name="Milk", category=dairy)
    milk.regions.set([france])
    saw = Product.objects.create(name="Saw", category=saws)
    saw.regions.set([tokyo])
    novel = Product.objects.create(name="Novel", category=books)
    loose = Product.objects.create(name="Loose", category=None)
    for product in (pie, milk, saw, novel, loose):
        Listing.objects.create(title=f"{product.name} listing", product=product)
    return Catalog(
        everything,
        food,
        fruit,
        apples,
        dairy,
        tools,
        saws,
        books,
        world,
        europe,
        france,
        lyon,
        asia,
        japan,
        tokyo,
        pie,
        milk,
        saw,
        novel,
        loose,
    )


def make_user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123", **flags)
    for slug in roles:
        assign_role(user, slug)
    return user


def fresh(user: Any, **attributes: Any) -> Any:
    """The same user as a new instance (what the next request sees), with extra attributes."""
    found = get_user_model().objects.get(pk=user.pk)
    for name, value in attributes.items():
        setattr(found, name, value)
    return found
