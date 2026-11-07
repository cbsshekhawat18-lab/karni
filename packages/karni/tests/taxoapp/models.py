"""A product catalog tagged to two trees, for ``tests/taxonomy/``.

* ``Region`` — a tree (unordered), named in files by its unique ``code``;
* ``Category`` — an ordered tree, named by its unique ``slug``;
* ``Product`` — ``taxonomies = {"region": ..., "category": ...}``: both
  many-to-manys are generated;
* ``Supplier`` — ``taxonomies = {"region": ...}`` over a many-to-many it
  declares itself (adopted), with a reverse accessor.

The keys follow ``KARNI_TEST_PK`` (``ApiBase``). No viewset is autodiscovered:
``tests.taxonomy.urls`` mounts them.
"""

from __future__ import annotations

from django.db import models

from karni.models import OrderedTreeModel, TreeModel
from tests.testapp.models import ApiBase


class Region(TreeModel, ApiBase):
    """A region tree: World > Europe > France > Lyon, and so on."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)

    def __str__(self) -> str:
        return self.name


class Category(OrderedTreeModel, ApiBase):
    """A category tree whose siblings have a position."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True)

    def __str__(self) -> str:
        return self.name


class Product(ApiBase):
    """Tagged to both trees: Karni generates ``region`` and ``category``."""

    name = models.CharField(max_length=100)
    price = models.PositiveIntegerField(default=0)

    class Karni:
        taxonomies = {"region": "taxoapp.Region", "category": "taxoapp.Category"}
        import_key = "name"

    def __str__(self) -> str:
        return self.name


class Supplier(ApiBase):
    """Tagged to the region tree through a many-to-many of its own (adopted)."""

    name = models.CharField(max_length=100)
    region = models.ManyToManyField(Region, blank=True, related_name="suppliers")

    class Karni:
        taxonomies = {"region": Region}

    def __str__(self) -> str:
        return self.name
