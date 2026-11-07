"""A tree model's admin changelist: tree order, names indented by depth, applied automatically."""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.utils.module_loading import import_string

from karni.admin.tree import DEPTH_ATTR
from tests.testapp.models import Category, Region
from tests.tree.build import regions

pytestmark = pytest.mark.django_db

URL = reverse("admin:testapp_region_changelist")


def registered(model: Any) -> Any:
    return import_string(settings.KARNI_ADMIN_SITE)._registry[model]


def rows(response: Any) -> list[tuple[str, int | None]]:
    assert response.status_code == 200, response.content[:500]
    return [
        (row.name, getattr(row, DEPTH_ATTR, None)) for row in response.context["cl"].result_list
    ]


def test_the_derived_columns_start_with_the_indented_name() -> None:
    admin = registered(Region)
    assert admin.list_display[0] == "tree_label"
    assert "parent" not in admin.list_display and "name" not in admin.list_display
    assert admin.tree_label.short_description == "Name"
    assert registered(Category).list_display[0] == "tree_label"
    assert "position" not in registered(Category).list_display


def test_the_changelist_lists_the_tree_depth_first(admin_client: Client) -> None:
    regions()
    response = admin_client.get(URL)
    assert rows(response) == [
        ("World", 0),
        ("Europe", 1),
        ("France", 2),
        ("Paris", 3),
        ("Germany", 2),
        ("Berlin", 3),
        ("Asia", 0),
    ]
    html = response.content.decode()
    assert 'class="karni-tree-label" style="padding-left: 4.5rem">Paris<' in html


def test_search_keeps_what_it_can_nested_and_a_sort_is_flat(admin_client: Client) -> None:
    regions()
    found = rows(admin_client.get(URL, {"q": "e"}))  # Europe, France, Germany, Berlin
    assert found == [("Europe", 0), ("France", 1), ("Germany", 1), ("Berlin", 2)]
    by_code = admin_client.get(URL, {"o": "1"})
    assert all(depth is None for _name, depth in rows(by_code))


def test_pages_follow_tree_order(admin_client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    regions()
    monkeypatch.setattr(registered(Region), "list_per_page", 3)
    first = rows(admin_client.get(URL))
    second = rows(admin_client.get(URL, {"p": "2"}))
    third = rows(admin_client.get(URL, {"p": "3"}))
    assert [name for name, _ in first + second + third] == [
        "World",
        "Europe",
        "France",
        "Paris",
        "Germany",
        "Berlin",
        "Asia",
    ]
    assert second[0] == ("Paris", 3)


def test_tree_order_has_a_row_limit(admin_client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    regions()
    monkeypatch.setattr(registered(Region), "tree_changelist_max_rows", 5)
    assert all(depth is None for _name, depth in rows(admin_client.get(URL)))


def test_the_ordered_tree_follows_positions(admin_client: Client) -> None:
    shoes = Category.objects.create(name="Shoes")
    Category.objects.create(name="Boots", parent=shoes)
    clogs = Category.objects.create(name="Clogs", parent=shoes)
    clogs.move_to(shoes, position=0)
    response = admin_client.get(reverse("admin:testapp_category_changelist"))
    assert rows(response) == [("Shoes", 0), ("Clogs", 1), ("Boots", 1)]
