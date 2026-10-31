"""``karni check`` on the menu (experimental): each route has a page, each requirement a permission.

The frontend is a ``routes.tsx`` written to a temporary directory and named
in ``KARNI_NAVIGATION_PAGES``, the way a scaffold registers its pages.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.db import OperationalError
from pytest_django import Settings

from karni import navigation
from karni.exceptions import KarniCommandError
from karni.navigation import checks as nav_checks
from karni.navigation.checks import check_navigation, frontend_routes, route_served

from .conftest import MENU, store

pytestmark = pytest.mark.django_db

ROUTES = """\
import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
const routes = [
    createRoute({ getParentRoute: () => root, path: "/", component: HomePage }),
    // karni:spec routes start
    createRoute({ getParentRoute: () => root, path: "/products", component: ProductsPage }),
    createRoute({ getParentRoute: () => root, path: "/products/$id", component: ProductPage }),
    createRoute({ getParentRoute: () => root, path: '/categories', component: CategoriesPage }),
    createRoute({ getParentRoute: () => root, path: "/regions", component: RegionsPage }),
    createRoute({ getParentRoute: () => root, path: "/events", component: EventsPage }),
    // karni:spec routes end
];
"""


@pytest.fixture(autouse=True)
def _frontend(settings: Settings, tmp_path: Path) -> Path:
    routes = tmp_path / "routes.tsx"
    routes.write_text(ROUTES)
    settings.KARNI_NAVIGATION_PAGES = [str(routes)]
    settings.KARNI_NAVIGATION = MENU
    return routes


def _ids(messages: list[Any]) -> list[str]:
    return [message.id for message in messages]


def test_the_routes_are_the_path_entries_of_the_pages_files() -> None:
    assert frontend_routes() == [
        "/",
        "/products",
        "/products/$id",
        "/categories",
        "/regions",
        "/events",
    ]


def test_a_param_segment_takes_any_value_and_a_query_is_ignored() -> None:
    routes = ["/products/$id", "/files/$", "/"]
    assert route_served("/products/42", routes) and route_served("/products/42/", routes)
    assert route_served("/files/a/b", routes) and route_served("/?tab=new", routes)
    assert not route_served("/products", routes) and not route_served("/products/42/edit", routes)


def test_a_route_without_a_page_is_e533_with_the_closest_route() -> None:
    found = check_navigation()  # /account has no page in ROUTES
    assert _ids(found) == ["karni.E533"]
    assert "'Account' links to /account" in found[0].msg
    assert "No route is close to it." in found[0].msg
    typo = [{"label": "Catalog", "children": [{"label": "Products", "route": "/prodcts"}]}]
    (message,) = check_navigation(navigation.nodes_from_setting(typo))
    assert message.id == "karni.E533"
    assert "'Catalog > Products' links to /prodcts" in message.msg
    assert "The closest route is /products." in message.msg
    assert "karni make page" in message.hint and "errors/#e533" in message.hint


def test_a_requirement_naming_no_permission_is_e534() -> None:
    nodes = navigation.nodes_from_setting(
        [
            {"label": "Products", "route": "/products", "requires": "testapp.prodct:view"},
            {"label": "Regions", "route": "/regions", "requires": "testapp.*:view"},
            {"label": "Home", "route": "/", "requires": "*"},
        ]
    )
    (message,) = check_navigation(nodes)
    assert message.id == "karni.E534"
    assert "'Products' requires 'testapp.prodct:view'" in message.msg


def test_the_database_menu_is_checked_where_the_database_answers(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = "db"
    assert check_navigation() == []
    store(MENU)
    assert _ids(check_navigation()) == ["karni.E533"]


def test_a_database_that_does_not_answer_is_w630(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.KARNI_NAVIGATION = "db"

    def refuse(using: Any = None) -> Any:
        raise OperationalError("connection refused")

    monkeypatch.setattr(navigation, "nodes_from_db", refuse)
    (message,) = check_navigation()
    assert message.id == "karni.W630" and "(connection refused)" in message.msg


def test_no_pages_file_is_w631_and_an_empty_list_turns_it_off(
    settings: Settings, tmp_path: Path
) -> None:
    settings.KARNI_NAVIGATION_PAGES = [str(tmp_path / "missing.tsx")]
    assert _ids(check_navigation()) == ["karni.W631"]
    settings.KARNI_NAVIGATION_PAGES = []
    assert check_navigation() == []


def test_a_relative_pages_file_is_read_from_the_project_root(
    settings: Settings, tmp_path: Path
) -> None:
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "routes.tsx").write_text('path: "/account",')
    settings.BASE_DIR = tmp_path
    settings.KARNI_NAVIGATION_PAGES = ["frontend/src/routes.tsx"]
    assert frontend_routes() == ["/account"]


def test_silenced_codes_are_left_out(settings: Settings) -> None:
    settings.SILENCED_SYSTEM_CHECKS = ["karni.E533"]
    assert check_navigation() == []


def test_nothing_to_check_while_the_menu_is_off(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = None
    assert check_navigation() == []


def test_karni_check_fails_on_the_menu(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "karni.management.commands.karni_check.entry_points", lambda **kw: []
    )  # the architecture hooks have their own tests
    settings.KARNI_NAVIGATION = [{"label": "Products", "route": "/products"}]
    out, err = StringIO(), StringIO()
    call_command("karni_check", stdout=out, stderr=err)
    assert "backend checks: ok" in out.getvalue()
    settings.KARNI_NAVIGATION = MENU
    with pytest.raises(KarniCommandError):
        call_command("karni_check", stdout=out, stderr=err)
    assert "navigation: karni.E533: Navigation item 'Account'" in err.getvalue()
    settings.KARNI_NAVIGATION_PAGES = ["/nowhere/routes.tsx"]
    out = StringIO()
    call_command("karni_check", stdout=out, stderr=StringIO())
    assert "navigation: karni.W631" in out.getvalue()


def test_the_failures_render_with_their_hint() -> None:
    errors, warnings = nav_checks.navigation_check_failures()
    assert warnings == [] and errors[0].startswith("karni.E533: ")
    assert "\n\tHINT: " in errors[0]
