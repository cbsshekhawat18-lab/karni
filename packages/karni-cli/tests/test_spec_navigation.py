"""``navigation:`` of ``karni.yaml`` (experimental): the menu karni build writes to KARNI_NAVIGATION.

A product catalog: products anyone may read, categories for signed-in
users, regions behind a role (their view permission), and two named pages.
"""

from __future__ import annotations

import textwrap
from typing import Any

from karni_cli.builder import render
from karni_cli.spec import navigation, normal
from karni_cli.spec.schema import Spec
from karni_cli.spec.validate import validate_text

SPEC = """\
version: 1
app: {name: Catalog}
roles:
  staff: {name: Staff, system: true, grants: {"*": all}}
apps:
  shop:
    entities:
      Product:
        fields: {name: str}
        access: {read: public, write: "role:staff"}
      Category:
        fields: {name: str}
        access: {read: authenticated, write: "role:staff"}
      Region:
        fields: {name: str}
        access: {read: "role:staff", write: "role:staff"}
      LineItem:
        fields: {name: str}
pages:
  - home: dashboard
  - Product: [list, detail, form]
  - Category: [list]
  - Region: [list]
  - LineItem: [detail]
  - reports: code
  - login: login
"""


def _spec(navigation_text: str = "") -> Spec:
    report = validate_text(SPEC + textwrap.dedent(navigation_text))
    assert report.ok and report.spec is not None, [i.render("spec") for i in report.issues]
    return report.spec


def test_no_navigation_writes_no_menu() -> None:
    spec = _spec()
    assert navigation.menu(spec) is None
    assert "KARNI_NAVIGATION" not in render.settings_block(spec, 100)
    assert normal.normalise(spec)["navigation"] is None


def test_true_is_every_page_with_a_route_in_order() -> None:
    menu = navigation.menu(_spec("navigation: true\n"))
    assert menu == [
        {"label": "Home", "route": "/", "requires": "authenticated"},
        {"label": "Products", "route": "/products", "requires": "public"},
        {"label": "Categories", "route": "/categories", "requires": "authenticated"},
        {"label": "Regions", "route": "/regions", "requires": "shop.region:view"},
        {"label": "Reports", "route": "/reports", "requires": "authenticated"},
    ]  # LineItem has no list page, and a sign-in page is no menu entry


def test_a_list_gives_the_order_groups_and_options() -> None:
    menu = navigation.menu(
        _spec(
            """\
            navigation:
              - home: {icon: home}
              - Catalog:
                  - Category
                  - Product: {label: All products, icon: box}
              - Admin: {icon: settings, items: [Region, reports]}
              - login
            """
        )
    )
    assert menu == [
        {"label": "Home", "route": "/", "icon": "home", "requires": "authenticated"},
        {
            "label": "Catalog",
            "requires": "public",  # one of its entries is public
            "children": [
                {"label": "Categories", "route": "/categories", "requires": "authenticated"},
                {
                    "label": "All products",
                    "route": "/products",
                    "icon": "box",
                    "requires": "public",
                },
            ],
        },
        {
            "label": "Admin",
            "icon": "settings",
            "requires": "authenticated",
            "children": [
                {"label": "Regions", "route": "/regions", "requires": "shop.region:view"},
                {"label": "Reports", "route": "/reports", "requires": "authenticated"},
            ],
        },
        {"label": "Login", "route": "/login", "requires": "public"},
    ]
    assert navigation.summary(menu) == (
        "Home /, Catalog (Categories /categories, All products /products), "
        "Admin (Regions /regions, Reports /reports), Login /login"
    )


def test_requires_replaces_the_default() -> None:
    menu = navigation.menu(
        _spec(
            """\
            navigation:
              - Product: {requires: "shop.product:change"}
              - Staff: {requires: "shop.*:change", items: [Region]}
            """
        )
    )
    assert menu is not None
    assert menu[0]["requires"] == "shop.product:change"
    assert menu[1]["requires"] == "shop.*:change"


def test_the_settings_block_writes_the_menu() -> None:
    block = render.settings_block(_spec("navigation: [home, Product]\n"), 100)
    assert "KARNI_NAVIGATION = [\n" in block
    assert '    {"label": "Products", "route": "/products", "requires": "public"},\n' in block
    namespace: dict[str, Any] = {}
    exec(block.split("KARNI_NAVIGATION = ", 1)[1].join(["menu = ", ""]), namespace)  # noqa: S102
    assert namespace["menu"] == navigation.menu(_spec("navigation: [home, Product]\n"))


def test_true_and_the_list_it_means_normalise_the_same() -> None:
    explicit = "navigation: [home, Product, Category, Region, reports]\n"
    assert normal.normalise(_spec("navigation: true\n")) == normal.normalise(_spec(explicit))


def test_export_maps_the_setting_back_to_entries() -> None:
    spec = _spec(
        """\
        navigation:
          - home: {icon: home}
          - Catalog: [Category, {Product: {label: All products}}]
          - Admin: {icon: settings, items: [Region]}
          - Staff only: {requires: "shop.region:view", items: [reports]}
        """
    )
    setting = navigation.menu(spec)
    left_out: list[str] = []
    entries = navigation.entries_from_setting(setting, navigation.pages(spec), left_out)
    assert left_out == []
    assert entries == [
        {"home": {"icon": "home"}},
        {"Catalog": ["Category", {"Product": {"label": "All products"}}]},
        {"Admin": {"icon": "settings", "items": ["Region"]}},
        {"Staff only": {"requires": "shop.region:view", "items": ["reports"]}},
    ]
    again = validate_text(SPEC + "navigation: " + repr(entries).replace("'", '"') + "\n")
    assert again.ok and again.spec is not None
    assert navigation.menu(again.spec) == setting


def test_export_lists_what_the_spec_cannot_say() -> None:
    spec = _spec()
    left_out: list[str] = []
    known = navigation.pages(spec)
    setting = [
        {"label": "Elsewhere", "route": "/elsewhere"},
        {"label": "reports", "children": [{"label": "Regions", "route": "/regions"}]},
        {"label": "Empty", "children": [{"label": "Gone", "route": "/gone"}]},
        {"label": "Products", "route": "/products", "requires": "public", "order": -1},
        {"label": "Products again", "route": "/products"},
    ]
    entries = navigation.entries_from_setting(setting, known, left_out)
    assert entries == ["Product"]  # order -1 first, then nothing else the spec can name
    assert left_out == [
        "navigation: Elsewhere at /elsewhere, a route no page of the spec has",
        "navigation: the group reports, whose label names a page",
        "navigation: Gone at /gone, a route no page of the spec has",
        "navigation: the group Empty, with no entry the spec can name",
        "navigation: Products again at /products, a second entry for it",
    ]
    db: list[str] = []
    assert navigation.entries_from_setting("db", known, db) is None
    assert "a menu the admin edits" in db[0]
    assert navigation.entries_from_setting(None, known, []) is None
