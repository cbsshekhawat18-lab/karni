"""The taxonomy suite's world: a region tree, a category tree, products and suppliers on them."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.test import override_settings

from tests.taxoapp.models import Category, Product, Region, Supplier


@pytest.fixture(autouse=True)
def _urls() -> Iterator[None]:
    with override_settings(
        ROOT_URLCONF="tests.taxonomy.urls", KARNI_API_ROUTER="tests.taxonomy.urls.get_router"
    ):
        yield


@dataclass
class Catalog:
    """Regions: World > (Europe > (France > Lyon, Spain, Hidden > Deep), Asia > Japan).

    Categories: Everything > (Food > Fruit, Tools). ``Hidden`` is the one
    region the ``regions`` resource does not let anyone read, and the
    ``Secret plan`` product the one only staff read.
    """

    world: Region
    europe: Region
    france: Region
    lyon: Region
    spain: Region
    hidden: Region
    deep: Region
    asia: Region
    japan: Region
    everything: Category
    food: Category
    fruit: Category
    tools: Category
    pie: Product
    wine: Product
    ham: Product
    saw: Product
    secret: Product
    sunk: Product
    loose: Product
    acme: Supplier
    zen: Supplier

    @staticmethod
    def ids(*nodes: Any) -> str:
        return ",".join(str(node.pk) for node in nodes)


def _region(name: str, code: str, parent: Region | None = None) -> Region:
    return Region.objects.create(name=name, code=code, parent=parent)


def _category(name: str, parent: Category | None = None) -> Category:
    return Category.objects.create(name=name, slug=name.lower(), parent=parent)


def _product(name: str, regions: list[Region], categories: list[Category]) -> Product:
    product = Product.objects.create(name=name, price=len(name))
    product.region.set(regions)
    product.category.set(categories)
    return product


@pytest.fixture
def catalog(db: Any) -> Catalog:
    world = _region("World", "w")
    europe = _region("Europe", "eu", world)
    france = _region("France", "fr", europe)
    lyon = _region("Lyon", "ly", france)
    spain = _region("Spain", "es", europe)
    hidden = _region("Hidden", "hidden", europe)
    deep = _region("Deep", "deep", hidden)
    asia = _region("Asia", "as", world)
    japan = _region("Japan", "jp", asia)
    everything = _category("Everything")
    food = _category("Food", everything)
    fruit = _category("Fruit", food)
    tools = _category("Tools", everything)
    acme = Supplier.objects.create(name="Acme")
    acme.region.set([france])
    zen = Supplier.objects.create(name="Zen")
    zen.region.set([japan])
    return Catalog(
        world=world,
        europe=europe,
        france=france,
        lyon=lyon,
        spain=spain,
        hidden=hidden,
        deep=deep,
        asia=asia,
        japan=japan,
        everything=everything,
        food=food,
        fruit=fruit,
        tools=tools,
        pie=_product("Pie", [lyon], [fruit]),
        wine=_product("Wine", [france, lyon], [food]),
        ham=_product("Ham", [spain], [food]),
        saw=_product("Saw", [japan], [tools]),
        secret=_product("Secret plan", [france], [tools]),
        sunk=_product("Sunk", [deep], []),
        loose=_product("Loose", [], []),
        acme=acme,
        zen=zen,
    )
