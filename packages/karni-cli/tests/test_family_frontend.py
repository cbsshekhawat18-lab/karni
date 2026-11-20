"""The family's frontend karni build writes for a project of parts (karni_cli.builder.family).

Rendered into a workspace with the scaffold's frontend: the family pages whose provider the
project holds, their routes in the Karni block, the one layout and home, parts.ts with the
family's registrations, and the scaffold's layout and home turned into re-exports while they
are still what karni new wrote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from karni_cli.builder import family, render
from karni_cli.generators.core import Workspace
from karni_cli.spec import navigation, schema

from .conftest import TEMPLATE

FRONTEND = TEMPLATE / "{{cookiecutter.project_slug}}" / "frontend" / "src"


def _spec(**over: Any) -> schema.Spec:
    data: dict[str, Any] = {
        "version": 1,
        "app": {"name": "Corner Shop", "kind": "app", "recipes": ["shop"]},
        "modules": {"payments": {}, "commerce": {}},
        "features": {"people": True, "preferences": True, "notify": True},
    }
    data.update(over)
    return schema.Spec.model_validate(data)


def _workspace(tmp_path: Path, name: str = "Corner Shop") -> Workspace:
    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    for rel in ("routes.tsx", "layout.tsx", "pages/home.tsx"):
        text = (FRONTEND / rel).read_text(encoding="utf-8")
        (src / rel).write_text(text.replace("{{ cookiecutter.project_name }}", name))
    return Workspace(tmp_path)


def _render(ws: Workspace, spec: schema.Spec, scaffold: dict[str, str] | None = None) -> Any:
    inputs = render.Inputs(
        spec=spec, pk="uuid", entities=set(), pages=set(), adopted=set(), scaffold=scaffold or {}
    )
    out = render.Output(ws)
    render._render_pages(ws, out, inputs)  # the frontend part of render(): no settings here
    render.render_parts(ws, out, inputs)
    return out


def test_a_shop_alone_gets_every_family_page_its_providers_give(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    out = _render(ws, _spec())
    names = {Path(rel).stem for rel in out.files if rel.startswith("frontend/src/karni/pages/")}
    assert names == {
        "signin",
        "account",
        "search",
        "inbox",
        "settings",
        "people",
        "person",
        "cart",
        "checkout",
        "orders",
        "order-new",
        "order",
        "order-invoice",
        "order-packing-slip",
    }
    routes = ws.read("frontend/src/routes.tsx") or ""
    assert (
        'createRoute({ getParentRoute: () => root, path: "/cart", component: KarniCartPage, '
        'staticData: { public: true, area: "store" } }),'
    ) in routes
    assert 'path: "/people/$id", component: KarniPersonPage }' in routes
    assert 'import KarniInboxPage from "./karni/pages/inbox";' in routes
    # a shop alone: its people are its customers, the people who bought
    people = out.files["frontend/src/karni/pages/people.tsx"]
    assert 'label="Customers" filters={{ orders__gte: "1" }}' in people
    assert navigation.people_label(_spec()) == "Customers"
    layout = out.files[family.LAYOUT_FILE]
    assert "storeActions={<MiniCart />}" in layout and "                inbox\n" in layout
    parts = out.files[render.PARTS_FILE]
    assert "registerFamily({ people: true, notify: true });" in parts
    assert "registerCommerce();" in parts


def test_a_part_that_sells_nothing_gets_no_cart_and_people_by_their_name(tmp_path: Path) -> None:
    spec = _spec(
        app={"name": "Desk", "kind": "app", "recipes": ["crm", "booking"]},
        modules={},
        features={"people": True},
    )
    ws = _workspace(tmp_path, "Desk")
    out = _render(ws, spec)
    names = {Path(rel).stem for rel in out.files if rel.startswith("frontend/src/karni/pages/")}
    assert names == {"signin", "account", "search", "people", "person"}
    assert 'label="People" navigate' in out.files["frontend/src/karni/pages/people.tsx"]
    layout = out.files[family.LAYOUT_FILE]
    assert "commerce-ui" not in layout and "inbox" not in layout
    assert "registerFamily({ people: true, notify: false });" in out.files[render.PARTS_FILE]


def test_the_scaffold_layout_and_home_re_export_the_familys(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    out = _render(ws, _spec())
    assert ws.read(family.SCAFFOLD_LAYOUT) == family.reexport_text(family.SCAFFOLD_LAYOUT)
    assert ws.read(family.SCAFFOLD_HOME) == family.reexport_text(family.SCAFFOLD_HOME)
    assert out.project[family.SCAFFOLD_LAYOUT] == ["re-exports the family's"]


def test_a_layout_the_project_changed_stays_and_the_build_says_so(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    ws.write(family.SCAFFOLD_LAYOUT, "export default function Mine() { return null; }\n")
    out = _render(ws, _spec())
    assert "Mine" in (ws.read(family.SCAFFOLD_LAYOUT) or "")
    assert "is the project's own" in out.project[family.SCAFFOLD_LAYOUT][0]


def test_a_recorded_scaffold_digest_counts_as_the_scaffold(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, "Another Name")  # not the spec's name: only the digest matches
    current = ws.read(family.SCAFFOLD_LAYOUT) or ""
    _render(ws, _spec(), scaffold={family.SCAFFOLD_LAYOUT: family.digest(current)})
    assert ws.read(family.SCAFFOLD_LAYOUT) == family.reexport_text(family.SCAFFOLD_LAYOUT)


def test_a_family_path_the_project_routes_itself_keeps_its_page(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    routes = ws.read("frontend/src/routes.tsx") or ""
    ws.write(
        "frontend/src/routes.tsx",
        routes.replace(
            "    // karni:routes",
            '    createRoute({ getParentRoute: () => root, path: "/cart", component: MyCart }),\n'
            "    // karni:routes",
        ),
    )
    out = _render(ws, _spec())
    assert "frontend/src/karni/pages/cart.tsx" not in out.files
    assert "KarniCartPage" not in (ws.read("frontend/src/routes.tsx") or "")


def test_a_project_without_parts_gets_no_family_file(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    out = _render(ws, _spec(app={"name": "Corner Shop", "kind": "app"}))
    assert not [rel for rel in out.files if rel.startswith("frontend/src/karni/")]
    assert "Layout" in (ws.read(family.SCAFFOLD_LAYOUT) or "")


@pytest.mark.parametrize("name", ["signin", "inbox"])
def test_the_family_pages_a_menu_may_name(name: str) -> None:
    pages = navigation.family_pages(_spec())
    assert pages[name].route == f"/{name}"
    assert pages["signin"].requires == "public"
