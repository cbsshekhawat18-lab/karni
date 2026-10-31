"""Navigation from data (experimental): whose menu shows what, from the grants the API reads.

The menu is a product catalog's (``conftest.MENU``) over ``tests.testapp``:
Products and Categories under a Catalog group, Regions, Events and Account.
Each requirement is read through ``grants_for``, the grants ``Granted()``
and ``user.can`` read: role grants and live per-user grants.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from pytest_django import Settings

from karni import navigation
from karni.accounts import grants
from karni.exceptions import KarniImproperlyConfigured
from karni.navigation import NavNode, menu_for, nodes_from_setting, opens, payload

from .conftest import MENU, fresh, make_user, store

pytestmark = pytest.mark.django_db


def _labels(nodes: list[NavNode]) -> list[Any]:
    return [
        node.label if node.route else (node.label, _labels(list(node.children))) for node in nodes
    ]


@pytest.fixture(autouse=True)
def _menu(settings: Settings, roles: None) -> None:
    settings.KARNI_NAVIGATION = MENU


# reading the setting


def test_siblings_sort_by_order_then_by_place() -> None:
    nodes = nodes_from_setting()
    assert [node.label for node in nodes] == ["Home", "Catalog", "Regions", "Events", "Account"]
    catalog = nodes[1]
    assert catalog.is_group and [child.label for child in catalog.children] == [
        "Categories",
        "Products",
    ]
    assert nodes[-1].requires == "authenticated" and nodes[-1].icon is None


def test_an_invalid_menu_is_e530_when_read() -> None:
    with pytest.raises(KarniImproperlyConfigured) as caught:
        nodes_from_setting([{"label": "Products", "route": "products"}])
    assert caught.value.code == "E530"


@pytest.mark.parametrize(
    ("menu", "fragment"),
    [
        ("everything", "must be a list"),
        ([{"route": "/products"}], "['label']"),
        ([{"label": "Products", "route": "products"}], "starts with '/'"),
        ([{"label": "Products"}], "neither a route nor children"),
        ([{"label": "Catalog", "route": "/c", "children": [{"label": "A", "route": "/a"}]}],
         "a route and children"),
        ([{"label": "Products", "route": "/p", "colour": "red"}], "unknown keys ['colour']"),
        ([{"label": "Products", "route": "/p", "icon": "Big Box"}], "icon 'Big Box'"),
        ([{"label": "Products", "route": "/p", "order": "1"}], "must be an integer"),
        ([{"label": "Products", "route": "/p", "requires": "staff"}], "(E532)"),
        ([{"label": "Catalog", "children": [{"label": "P", "route": "x"}]}],
         "KARNI_NAVIGATION[0]['children'][0]"),
    ],
)  # fmt: skip
def test_each_problem_of_the_setting_is_named(menu: Any, fragment: str) -> None:
    problems = navigation.settings_problems(menu)
    assert any(fragment in problem for problem in problems), problems


def test_the_database_source_needs_its_app() -> None:
    assert navigation.settings_problems("db", ["karni", "karni.navigation"]) == []
    assert navigation.settings_problems("db", ["karni.navigation.apps.KarniNavigationConfig"]) == []
    (problem,) = navigation.settings_problems("db", ["karni"])
    assert problem.endswith("(E531)")


# whose menu


def test_a_visitor_sees_the_public_entries_only() -> None:
    assert _labels(menu_for(AnonymousUser())) == ["Home"]
    assert _labels(menu_for(None)) == ["Home"]


def test_a_user_without_roles_sees_public_and_authenticated_entries() -> None:
    assert _labels(menu_for(make_user("reader@example.com"))) == ["Home", "Account"]


def test_role_grants_open_items_and_their_group() -> None:
    editor = make_user("editor@example.com", "catalog_editor")
    assert _labels(menu_for(editor)) == [
        "Home",
        ("Catalog", ["Categories", "Products"]),
        "Account",
    ]
    organizer = make_user("organizer@example.com", "organizer")
    assert _labels(menu_for(organizer)) == ["Home", "Events", "Account"]  # testapp.event:*


def test_a_superuser_sees_every_entry() -> None:
    root = make_user("root@example.com", is_superuser=True, is_staff=True)
    assert _labels(menu_for(root)) == [
        "Home",
        ("Catalog", ["Categories", "Products"]),
        "Regions",
        "Events",
        "Account",
    ]


def test_a_group_whose_entries_are_all_hidden_is_left_out(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = [
        {
            "label": "Admin",
            "requires": "public",
            "children": [
                {
                    "label": "Setup",
                    "children": [
                        {"label": "Regions", "route": "/regions", "requires": "testapp.region:view"}
                    ],
                },
            ],
        },
        {"label": "Home", "route": "/", "requires": "public"},
    ]
    assert _labels(menu_for(make_user("reader@example.com"))) == ["Home"]
    root = make_user("root@example.com", is_superuser=True)
    assert _labels(menu_for(root)) == [("Admin", [("Setup", ["Regions"])]), "Home"]


def test_a_group_requirement_closes_its_entries(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = [
        {
            "label": "Catalog",
            "requires": "testapp.category:view",
            "children": [{"label": "Account", "route": "/account"}],
        }
    ]
    assert menu_for(make_user("reader@example.com")) == []
    editor = make_user("editor@example.com", "catalog_editor")
    assert _labels(menu_for(editor)) == [("Catalog", ["Account"])]


def test_a_user_grant_opens_an_item_and_its_expiry_closes_it(settings: Settings) -> None:
    settings.KARNI_USER_GRANTS = True
    reader = make_user("reader@example.com")
    assert "Regions" not in _labels(menu_for(reader))
    row = grants.grant(None, reader, "testapp.region:view", reason="the regional report")
    assert "Regions" in _labels(menu_for(fresh(reader)))
    grants.expire(None, row, timezone.now() - timedelta(seconds=1))
    assert "Regions" not in _labels(menu_for(fresh(reader)))


def test_a_user_grant_with_a_later_expiry_is_live(settings: Settings) -> None:
    settings.KARNI_USER_GRANTS = True
    reader = make_user("reader@example.com")
    grants.grant(
        None, reader, "testapp.product:view", expires_at=timezone.now() + timedelta(days=1)
    )
    assert _labels(menu_for(fresh(reader))) == ["Home", ("Catalog", ["Products"]), "Account"]


def test_user_grants_count_only_while_the_switch_is_on(settings: Settings) -> None:
    reader = make_user("reader@example.com")
    settings.KARNI_USER_GRANTS = True
    grants.grant(None, reader, "testapp.region:view")
    settings.KARNI_USER_GRANTS = False
    assert "Regions" not in _labels(menu_for(fresh(reader)))


def test_opens_reads_the_same_grants_as_user_can() -> None:
    editor = make_user("editor@example.com", "catalog_editor")
    assert opens("testapp.product:change", editor) is editor.can("testapp.product:change")
    assert opens("testapp.*:view", editor) and not opens("testapp.region:*", editor)
    assert opens("*", editor) and not opens("*", make_user("reader@example.com"))
    assert not opens("testapp.product:view", AnonymousUser())


# what it costs


def _count(user: Any) -> int:
    with CaptureQueriesContext(connection) as queries:
        menu_for(user)
    return len(queries)


def test_the_query_count(settings: Settings) -> None:
    assert _count(AnonymousUser()) == 0
    settings.KARNI_NAVIGATION = [{"label": "Account", "route": "/account"}]
    assert _count(fresh(make_user("reader@example.com"))) == 0  # no permission named
    settings.KARNI_NAVIGATION = MENU
    editor = make_user("editor@example.com", "catalog_editor")
    assert _count(fresh(editor)) == 1  # the role grants
    settings.KARNI_USER_GRANTS = True
    assert _count(fresh(editor)) == 2  # and the user grants
    store(MENU)
    settings.KARNI_NAVIGATION = "db"
    assert _count(fresh(editor)) == 3  # and the rows
    settings.KARNI_USER_GRANTS = False
    assert _count(fresh(editor)) == 2
    root = make_user("root@example.com", is_superuser=True)
    assert _count(fresh(root)) == 1  # the rows: a superuser holds every permission without one


def test_the_grants_load_once_per_user_instance() -> None:
    editor = fresh(make_user("editor@example.com", "catalog_editor"))
    menu_for(editor)
    assert _count(editor) == 0


# the two sources


def test_both_sources_give_the_same_response(settings: Settings) -> None:
    users = [
        AnonymousUser(),
        make_user("reader@example.com"),
        make_user("editor@example.com", "catalog_editor"),
        make_user("organizer@example.com", "organizer"),
        make_user("root@example.com", is_superuser=True),
    ]
    from_settings = [payload(fresh(u) if u.pk else u) for u in users]
    store(MENU)
    settings.KARNI_NAVIGATION = "db"
    from_rows = [payload(fresh(u) if u.pk else u) for u in users]
    assert from_rows == from_settings
    assert from_settings[2] == {
        "items": [
            {"label": "Home", "icon": "home", "route": "/", "children": []},
            {
                "label": "Catalog",
                "icon": "box",
                "route": None,
                "children": [
                    {"label": "Categories", "icon": None, "route": "/categories", "children": []},
                    {"label": "Products", "icon": None, "route": "/products", "children": []},
                ],
            },
            {"label": "Account", "icon": None, "route": "/account", "children": []},
        ]
    }


def test_the_database_menu_follows_moves_and_hides_deleted_branches(settings: Settings) -> None:
    from karni.navigation.models import NavItem

    store(MENU)
    settings.KARNI_NAVIGATION = "db"
    root = make_user("root@example.com", is_superuser=True)
    products = NavItem.objects.get(label="Products")
    products.move_to(products.parent, position=0)
    catalog = NavItem.objects.get(label="Catalog")
    assert _labels(menu_for(fresh(root)))[1] == ("Catalog", ["Products", "Categories"])
    regions = NavItem.objects.get(label="Regions")
    regions.move_to(None, position=0)
    assert _labels(menu_for(fresh(root)))[0] == "Regions"
    catalog.delete_branch()
    assert "Catalog" not in str(_labels(menu_for(fresh(root))))


def test_a_project_menu_from_its_own_source() -> None:
    nodes = [NavNode("Reports", "/reports", requires="testapp.event:view")]
    assert payload(make_user("organizer@example.com", "organizer"), nodes) == {
        "items": [{"label": "Reports", "icon": None, "route": "/reports", "children": []}]
    }
    assert payload(AnonymousUser(), nodes) == {"items": []}
