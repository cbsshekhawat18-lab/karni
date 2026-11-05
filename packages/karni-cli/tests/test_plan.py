"""``karni plan`` (experimental): what ``karni build`` would change, writing nothing.

Two real projects, each made once per module: an empty one (the template
alone) for the fixture's plan, and one built from :data:`BASE` with
``karni make`` (as A1's round trip does), migrated on SQLite and given rows,
so the risky changes are counted by the project's own ``manage.py
karni_rows``. Most tests plan against that project's facts, read once.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli.main import app
from karni_cli.spec import plan as plan_mod
from karni_cli.spec.export import build, read_facts
from karni_cli.spec.plan import Change, Plan, apply_counts, manage_counter, plan_project
from karni_cli.spec.validate import validate_text

from .conftest import REPO_ROOT, TEMPLATE
from .test_spec import FIXTURE, _build_from_spec

PLAN_SCHEMA = REPO_ROOT / "docs" / "assets" / "karni-plan.schema.json"
SNAPSHOT = Path(__file__).parent / "fixtures" / "spec" / "harbour-yoga.plan.json"
#: The fixture's plan on an empty project, in cl100k tokens (measured 396).
TOKEN_BUDGET = 600

BASE = """\
version: 1
app: {name: Plan Base}
roles:
  staff: {name: Staff, system: true, grants: {"*": all}}
  member: {name: Member, default: true, grants: {shop.order: own}}
apps:
  shop:
    entities:
      Product:
        fields:
          name: "str:120"
          sku: "str:20"
          note: text?
          tag: choice:new|old
          kind: str:30?
        search: name
        access: {read: "role:staff", write: "role:staff"}
      Supplier:
        fields: {name: str}
      Order:
        fields:
          product: fk:Product
          buyer: fk:User
          supplier: fk:Supplier?
          status: state:open>paid|paid>shipped
          qty: int
        owner: buyer
        access: {read: owned:buyer, write: owned:buyer}
pages:
  - home: dashboard
  - Product: [list]
seed: {Product: 5}
"""

ROWS = """\
from django.contrib.auth import get_user_model
from shop.models import Order, Product, Supplier
user = get_user_model().objects.create_user(email="buyer@example.com", password="x-12345678")
lamp = Product.objects.create(name="A long product name here", sku="L1", note="bright", tag="new", kind="x")
desk = Product.objects.create(name="Desk", sku="D1", note="oak", tag="old")
Product.objects.create(name="Lamp", sku="L2", tag="old")
Order.objects.create(product=lamp, buyer=user, qty=1)
Order.objects.create(product=desk, buyer=user, qty=2)
for name in ("North", "South", "East", "West"):
    Supplier.objects.create(name=name)
"""


def _manage(root: Path, *args: str) -> None:
    proc = project_mod.run_manage(root, list(args), docker=False, database=None)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _env(mp: pytest.MonkeyPatch, database: Path) -> None:
    mp.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    mp.setenv("DATABASE_URL", f"sqlite:///{database}")
    mp.setenv("PYTHONDONTWRITEBYTECODE", "1")
    for name in ("DJANGO_SETTINGS_MODULE", "KARNI_PAYMENTS_PROVIDER", "KARNI_2FA"):
        mp.delenv(name, raising=False)


def _render(parent: Path, name: str) -> Path:
    from cookiecutter.main import cookiecutter

    cookiecutter(
        str(TEMPLATE), no_input=True, extra_context={"project_name": name}, output_dir=str(parent)
    )
    return parent / name.lower().replace(" ", "_")


@pytest.fixture(autouse=True)
def _project_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The projects run on this interpreter (the suite's conftest turns that off per test)."""
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))


@dataclass
class Project:
    root: Path
    database: Path
    facts: dict[str, Any]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    """A project built from BASE, migrated, with rows: 3 products, 2 orders, 4 suppliers."""
    parent = tmp_path_factory.mktemp("plan-base")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KARNI_TEMPLATES", str(TEMPLATE))
        _env(mp, parent / "db.sqlite3")
        root = _render(parent, "Plan Base")
        mp.chdir(root)
        spec = validate_text(BASE).spec
        assert spec is not None
        _build_from_spec(root, spec)
        _manage(root, "makemigrations", "shop")
        _manage(root, "migrate", "--no-input")
        _manage(root, "shell", "-c", ROWS)
        yield Project(root, parent / "db.sqlite3", read_facts(root, docker=False))


def _plan(text: str, project: Project, *, counted: bool = False) -> Plan:
    report = validate_text(textwrap.dedent(text), databases=project.facts["databases"])
    assert report.ok and report.spec is not None, [i.render("spec") for i in report.issues]
    found = plan_project(report.spec, project.facts, project.root, file="karni.yaml")
    return apply_counts(found, manage_counter(project.root, docker=False) if counted else None)


def _edit(*pairs: tuple[str, str]) -> str:
    text = BASE
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def _only(plan: Plan, target: str) -> Change:
    (found,) = [change for change in plan.changes if change.target == target]
    return found


# the project as it is -------------------------------------------------------------


def test_the_projects_own_spec_plans_nothing(base: Project) -> None:
    plan = _plan(BASE, base)
    assert plan.changes == [], plan.text()
    assert plan.text() == "No changes: the project matches karni.yaml.\n"
    exported = build(base.facts, base.root)
    from karni_cli.spec.export import Exported

    again = _plan(Exported(exported.data).text(), base)
    assert again.changes == [], again.text()


def test_adding_a_field_an_entity_a_page_and_a_seed(base: Project) -> None:
    plan = _plan(
        _edit(
            ("        fields: {name: str}\n", '        fields: {name: str, city: "str:80?"}\n'),
            (
                "pages:\n",
                (
                    "      Invoice:\n        fields: {order: fk:Order, total: money:EUR}\n"
                    "        pk: bigint\npages:\n"
                ),
            ),
            ("  - Product: [list]\n", "  - Product: [list, detail]\n  - about: blank\n"),
            ("seed: {Product: 5}", "seed: {Product: 8, Invoice: 20}"),
        ),
        base,
    )
    lines = plan.text().splitlines()
    assert "  + shop.Supplier.city: str:80?" in lines
    assert "  + shop.Invoice: (order fk:Order, total money:EUR) pk bigint" in lines
    assert "  ~ Product: list -> list, detail" in lines and "  + about: blank" in lines
    assert "  + shop" in lines[lines.index("migrations") :]
    assert "  ~ Product: 5 -> 8" in lines and "  + Invoice: 20" in lines
    assert "  + shop/tests/karni/test_invoice.py" in lines
    assert not plan.risky and plan.row_counts == "not needed"
    assert lines[-1] == f"{len(plan.changes)} changes, 0 risky."


def test_related_tabs_and_a_dashboard_page(base: Project) -> None:
    """Experimental: a detail page's related tabs and a dashboard page other than home."""
    plan = _plan(
        _edit(
            (
                "  - Product: [list]\n",
                "  - Product: [list, {detail: {related: [Order]}}]\n  - overview: dashboard\n",
            ),
        ),
        base,
    )
    lines = plan.text().splitlines()
    assert "  ~ Product: list -> list, detail (related shop.Order.product)" in lines
    assert "  + overview: dashboard (rows per entity: Order, Product, Supplier)" in lines
    pages = [change for change in plan.changes if change.area == "pages"]
    assert all(change.managed for change in pages), pages
    # The scaffold's home page stays the project's: never built, so not managed.
    home = _plan(_edit(("  - home: dashboard\n", "")), base)
    assert [c.target for c in home.changes if c.area == "pages"] == ["home"]


def test_changing_a_field_safely_and_entity_options(base: Project) -> None:
    plan = _plan(
        _edit(
            ('          name: "str:120"\n', '          name: "str:200"\n'),
            ("          note: text?\n", "          note: text?\n          extra: json?\n"),
            ("        search: name\n", "        search: [name, sku]\n        order: -name\n"),
            ("      Supplier:\n", "      Supplier:\n        audit: true\n"),
        ),
        base,
    )
    assert _only(plan, "shop.Product.name").detail == "str:120 -> str:200"
    assert not _only(plan, "shop.Product.name").risky
    assert _only(plan, "shop.Product search").detail == "name -> name, sku"
    assert _only(plan, "shop.Product order").detail == "none -> -name"
    assert _only(plan, "shop.Supplier audit").detail == "false -> true"
    assert [c.target for c in plan.changes if c.area == "migrations"] == ["shop"]
    assert not plan.risky


def test_turning_on_per_user_grants_plans_its_setting(base: Project) -> None:
    plan = _plan(_edit(("roles:\n", "features: {user_grants: true}\nroles:\n")), base)
    change = _only(plan, "user_grants")
    assert (change.area, change.action, change.detail) == ("features", "add", "KARNI_USER_GRANTS")
    assert not change.risky
    assert "  + user_grants: KARNI_USER_GRANTS" in plan.text().splitlines()


def test_navigation_is_planned_as_the_setting_it_writes(base: Project) -> None:
    """The menu (experimental): a change in the pages area, named after KARNI_NAVIGATION."""
    import copy

    text = _edit(("seed: {Product: 5}\n", "navigation: true\nseed: {Product: 5}\n"))
    plan = _plan(text, base)
    change = _only(plan, "KARNI_NAVIGATION")
    assert (change.area, change.action, change.detail) == (
        "pages",
        "add",
        "Home /, Products /products",
    )
    assert not change.risky and change.managed
    assert "  + KARNI_NAVIGATION: Home /, Products /products" in plan.text().splitlines()
    report = validate_text(text)
    assert report.spec is not None
    facts = copy.deepcopy(base.facts)
    facts["settings"]["KARNI_NAVIGATION"] = [
        {"label": "Home", "route": "/", "requires": "authenticated"},
        {"label": "Products", "route": "/products", "requires": "shop.product:view"},
    ]
    same = plan_project(report.spec, facts, base.root, file="karni.yaml")
    assert [c for c in same.changes if c.target == "KARNI_NAVIGATION"] == [], same.text()
    assert build(facts, base.root).data["navigation"] == ["home", "Product"]
    regrouped = _edit(
        ("seed: {Product: 5}\n", "navigation: [home, {Shop: [Product]}]\nseed: {Product: 5}\n")
    )
    report = validate_text(regrouped)
    assert report.spec is not None
    changed = plan_project(report.spec, facts, base.root, file="karni.yaml")
    assert "  ~ KARNI_NAVIGATION: Home /, Shop (Products /products)" in changed.text()
    gone = plan_project(validate_text(BASE).spec, facts, base.root, file="karni.yaml")  # type: ignore[arg-type]
    assert "  - KARNI_NAVIGATION: Home /, Products /products" in gone.text()


def test_an_aggregate_is_an_option_without_a_migration(base: Project) -> None:
    plan = _plan(
        _edit(
            (
                "        search: name\n",
                (
                    "        search: name\n        aggregate:\n          group_by: [tag, kind]\n"
                    "          values: [name]\n          metrics: [count, distinct_count]\n"
                ),
            ),
            (
                "pages:\n",
                (
                    "      Invoice:\n        fields: {total: money:EUR}\n"
                    "        aggregate: {group_by: [created_at:month]}\npages:\n"
                ),
            ),
        ),
        base,
    )
    change = _only(plan, "shop.Product aggregate")
    assert change.detail == "none -> by tag, kind of name (count, distinct_count)"
    assert not change.risky
    assert "aggregate by created_at:month" in _only(plan, "shop.Invoice").detail
    assert [c.target for c in plan.changes if c.area == "migrations"] == ["shop"]  # Invoice only
    same = _plan(
        _edit(
            (
                "        search: name\n",
                (
                    "        search: name\n        aggregate: {group_by: tag, metrics: "
                    "[sum, avg, min, max, count, distinct_count]}\n"
                ),
            )
        ),
        base,
    )
    assert _only(same, "shop.Product aggregate").detail == "none -> by tag"


def test_api_cache_and_entity_cache(base: Project) -> None:
    plan = _plan(
        _edit(
            ("app: {name: Plan Base}\n", "app: {name: Plan Base}\nfeatures: {api_cache: true}\n"),
            ("        search: name\n", "        search: name\n        cache: 60\n"),
            ("      Supplier:\n", "      Supplier:\n        cache: false\n"),
            (
                "pages:\n",
                "      Brand:\n        fields: {name: str}\n        cache: false\npages:\n",
            ),
        ),
        base,
    )
    assert _only(plan, "api_cache").detail == "KARNI_API_CACHE"
    assert _only(plan, "shop.Product cache").detail == "none -> 60"
    assert _only(plan, "shop.Supplier cache").detail == "none -> false"
    assert _only(plan, "shop.Brand").detail == "(name str) cache false"
    assert "shop" in [c.target for c in plan.changes if c.area == "migrations"]  # Brand only
    assert not plan.risky
    # the change lands in the Karni-owned viewset file, so adopting that file unmanages it
    spec = validate_text(
        _edit(("        search: name\n", "        search: name\n        cache: 60\n"))
    ).spec
    assert spec is not None
    for adopted, managed in ((frozenset(), True), (frozenset({"shop/karni/api.py"}), False)):
        owned = plan_mod.Managed(entities=frozenset({"shop.Product"}), adopted=adopted)
        found = plan_project(spec, base.facts, base.root, file="karni.yaml", managed=owned)
        assert _only(found, "shop.Product cache").managed is managed
    ttl = _plan(
        _edit(
            (
                "app: {name: Plan Base}\n",
                "app: {name: Plan Base}\nfeatures:\n  api_cache: {ttl: 45}\n",
            )
        ),
        base,
    )
    assert _only(ttl, "api_cache").detail == "KARNI_API_CACHE, KARNI_API_CACHE_TTL 45"


def test_the_cache_of_a_project_is_exported_and_plans_nothing(base: Project) -> None:
    facts = json.loads(json.dumps(base.facts))
    facts["settings"] |= {"KARNI_API_CACHE": True, "KARNI_API_CACHE_TTL": 45}
    for viewset in facts["viewsets"]:
        if viewset["model"] == "shop.Product":
            viewset["cache"] = {"ttl": 60, "depends_on": []}
        elif viewset["model"] == "shop.Supplier":
            viewset["cache"] = {"uncached": "spec"}
    text = _edit(
        ("app: {name: Plan Base}\n", "app: {name: Plan Base}\nfeatures: {api_cache: {ttl: 45}}\n"),
        ("        search: name\n", "        search: name\n        cache: 60\n"),
        ("      Supplier:\n", "      Supplier:\n        cache: false\n"),
    )
    report = validate_text(text)
    assert report.ok and report.spec is not None, report.issues
    assert plan_project(report.spec, facts, base.root, file="karni.yaml").changes == []
    off = validate_text(BASE)
    assert off.spec is not None
    changes = plan_project(off.spec, facts, base.root, file="karni.yaml").changes
    assert {(c.target, c.detail) for c in changes} == {
        ("api_cache", "KARNI_API_CACHE"),
        ("shop.Product cache", "60 -> none"),
        ("shop.Supplier cache", "false -> none"),
    }
    assert [c.action for c in changes if c.target == "api_cache"] == ["remove"]
    longer = validate_text(text.replace("{ttl: 45}", "{ttl: 120}"))
    assert longer.spec is not None
    (change,) = plan_project(longer.spec, facts, base.root, file="karni.yaml").changes
    assert (change.action, change.detail) == ("change", "KARNI_API_CACHE_TTL 45 -> 120")


def test_global_search_is_shown_and_its_indexes_are_a_migration(base: Project) -> None:
    plan = _plan(
        _edit(
            ("        search: name\n", "        search: name\n        global_search: true\n"),
            (
                "      Supplier:\n        fields: {name: str}\n",
                (
                    "      Supplier:\n        fields: {name: str}\n"
                    "        global_search: {fields: [name], weight: 0.5}\n"
                ),
            ),
            (
                "pages:\n",
                (
                    "      Brand:\n        fields: {name: str, country: str}\n"
                    "        global_search: {fields: [name], subtitle: country}\npages:\n"
                ),
            ),
        ),
        base,
    )
    assert _only(plan, "shop.Product global_search").detail == "none -> name"
    assert _only(plan, "shop.Supplier global_search").detail == "none -> name (weight 0.5)"
    assert "global_search name (subtitle country)" in str(_only(plan, "shop.Brand").detail)
    assert [c.target for c in plan.changes if c.area == "migrations"] == ["shop"]
    assert not plan.risky


def test_only_a_change_of_the_searched_fields_writes_a_migration() -> None:
    from karni_cli.spec.plan import _search_indexes_change

    one = {"global_search": {"fields": ["name"], "title": "name", "subtitle": None, "weight": 1}}
    other = {"global_search": {**one["global_search"], "subtitle": "sku", "weight": 2.0}}
    assert not _search_indexes_change(one, other)  # class Karni only
    assert _search_indexes_change(one, {"global_search": None})  # the indexes go
    assert _search_indexes_change({}, one)
    assert not _search_indexes_change({}, {**one, "external": True})  # no migration touches it


def test_text_and_markdown_swap_safely_and_the_layout_keys(base: Project) -> None:
    """Experimental (wide models): the markdown type, groups and column sets."""
    plan = _plan(
        _edit(
            ("          note: text?\n", "          note: markdown?\n"),
            (
                "      Supplier:\n",
                (
                    "      Supplier:\n        groups: {Main: [name]}\n"
                    "        column_sets: {default: [name], codes: [id, name]}\n"
                ),
            ),
        ),
        base,
    )
    note = _only(plan, "shop.Product.note")
    assert note.detail == "text? -> markdown?" and not note.risky  # the same text column
    assert _only(plan, "shop.Supplier groups").detail == "none -> Main name"
    assert _only(plan, "shop.Supplier column_sets").detail == "none -> default name, codes id, name"
    assert not plan.risky
    required = _only(
        _plan(_edit(("          note: text?\n", "          note: markdown\n")), base),
        "shop.Product.note",
    )
    assert required.risky and required.reason == "it becomes required"


# risky changes ----------------------------------------------------------------------

#: (edit, target, reason fragment, rows counted from ROWS)
RISKY: list[tuple[tuple[tuple[str, str], ...], str, str, int]] = [
    ((("          note: text?\n", ""),), "shop.Product.note", "its values are lost", 2),
    ((('          name: "str:120"\n', '          name: "str:10"\n'),), "shop.Product.name",
     "values longer than 10 do not fit", 1),
    ((("          kind: str:30?\n", "          kind: str:30\n"),), "shop.Product.kind",
     "it becomes required", 2),
    ((("          tag: choice:new|old\n", "          tag: choice:new|used\n"),), "shop.Product.tag",
     "old is no longer a value", 2),
    ((("          qty: int\n", "          qty: str\n"),), "shop.Order.qty",
     "its type changes from int to str", 2),
    ((("          product: fk:Product\n", "          product: fk:User\n"),), "shop.Order.product",
     "it points at User instead of shop.Product", 2),
    ((("      Supplier:\n        fields: {name: str}\n", ""),
      ("          supplier: fk:Supplier?\n", "")), "shop.Supplier", "its table and rows are dropped", 4),
    ((("        owner: buyer\n", "        owner: buyer\n        pk: bigint\n"),), "shop.Order pk",
     "out of scope", 2),
    ((('        access: {read: "role:staff", write: "role:staff"}\n',
       '        access: {read: public, write: "role:staff"}\n'),), "shop.Product",
     "reads open to everyone", 3),
    ((("        access: {read: owned:buyer, write: owned:buyer}\n",
       "        access: {read: owned:buyer, write: authenticated}\n"),), "shop.Order",
     "writes open to every signed-in user", 2),
    ((("{shop.order: own}", "{shop.order: all}"),), "member grant shop.order",
     "the role reaches every row", 2),
]  # fmt: skip


@pytest.mark.parametrize(("edits", "target", "reason", "rows"), RISKY)
def test_each_risky_kind_without_row_counts(
    base: Project, edits: tuple[tuple[str, str], ...], target: str, reason: str, rows: int
) -> None:
    plan = _plan(_edit(*edits), base)
    change = _only(plan, target)
    assert change.risky and change.reason and reason in change.reason, change.line()
    assert change.rows is None and plan.row_counts == "offline"
    assert change.line().startswith("! ") and " rows)" not in change.line()
    assert "Row counts skipped: --offline." in plan.text()
    assert "karni build refuses the risky (!) changes without --allow-destructive." in plan.text()


def test_each_risky_kind_with_row_counts(base: Project) -> None:
    """One spec with every risky kind, counted in one manage.py karni_rows call."""
    edits = [pair for case in RISKY for pair in case[0] if pair[0] != '          name: "str:120"\n']
    edits = [pair for pair in edits if pair != ("          qty: int\n", "          qty: str\n")]
    edits = [p for p in edits if not p[0].startswith("        access: {read: owned")]
    edits = [p for p in edits if p[0] != "        owner: buyer\n"]
    plan = _plan(_edit(*edits), base, counted=True)
    assert plan.row_counts == "counted", plan.note
    for _edits, target, _reason, rows in RISKY:
        if target in ("shop.Product.name", "shop.Order.qty", "shop.Order", "shop.Order pk"):
            continue
        change = _only(plan, target)
        assert change.rows == rows, change.line()
        assert change.line().endswith(f" ({rows} rows)")
    for edits_one, target, _reason, rows in RISKY:
        if target in ("shop.Product.name", "shop.Order.qty", "shop.Order", "shop.Order pk"):
            change = _only(_plan(_edit(*edits_one), base, counted=True), target)
            assert change.rows == rows, change.line()


def test_a_module_removed_is_risky_with_its_tables(base: Project) -> None:
    facts = json.loads(json.dumps(base.facts))
    facts["modules"].append({"name": "approvals", "settings": {}, "defaults": {}})
    report = validate_text(BASE)
    assert report.spec is not None
    plan = plan_project(report.spec, facts, base.root, file="karni.yaml")
    asked: list[list[dict[str, Any]]] = []

    def counter(requests: list[dict[str, Any]]) -> dict[str, Any]:
        asked.append(requests)
        return {"rows": [5, 1], "unreachable": {}}

    apply_counts(plan, counter)
    change = _only(plan, "approvals")
    assert change.risky and change.action == "remove" and change.rows == 6
    assert asked == [
        [{"model": "karni_approvals.PendingChange"}, {"model": "karni_approvals.Decision"}]
    ]
    added = _plan(BASE.replace("roles:\n", "modules: {approvals: {required: 2}}\nroles:\n"), base)
    assert _only(added, "approvals").line() == "  + approvals: required 2"


def test_the_reports_module_is_planned_with_its_options(base: Project) -> None:
    added = _plan(
        BASE.replace("roles:\n", "modules: {reports: {page_size: letter, keep: 2}}\nroles:\n"),
        base,
    )
    change = _only(added, "reports")
    assert change.action == "add" and not change.risky
    assert change.line() == "  + reports: page_size letter, keep 2"
    facts = json.loads(json.dumps(base.facts))
    facts["modules"].append(
        {"name": "reports", "settings": {"KARNI_REPORTS_PAGE_SIZE": "A4"}, "defaults": {}}
    )
    report = validate_text(BASE)
    assert report.spec is not None
    plan = plan_project(report.spec, facts, base.root, file="karni.yaml")
    asked: list[list[dict[str, Any]]] = []

    def counter(requests: list[dict[str, Any]]) -> dict[str, Any]:
        asked.append(requests)
        return {"rows": [4], "unreachable": {}}

    apply_counts(plan, counter)
    removed = _only(plan, "reports")
    assert removed.risky and removed.action == "remove" and removed.rows == 4
    assert asked == [[{"model": "karni_reports.GeneratedReport"}]]


def test_the_ai_module_plans_with_its_provider_only(base: Project) -> None:
    """karni-ai's option in karni.yaml is the provider. Its model and key stay in .env."""
    added = _plan(BASE.replace("roles:\n", "modules: {ai: {provider: anthropic}}\nroles:\n"), base)
    change = _only(added, "ai")
    assert change.area == "modules" and change.action == "add" and not change.risky
    assert change.line() == "  + ai: provider anthropic"


def test_the_storage_module_is_planned_with_its_provider_and_protected_fields(
    base: Project,
) -> None:
    added = _plan(
        _edit(
            ("roles:\n", "modules: {storage: {provider: r2}}\nroles:\n"),
            (
                "          kind: str:30?\n",
                "          kind: str:30?\n          manual: file:protected?\n",
            ),
        ),
        base,
    )
    change = _only(added, "storage")
    assert change.action == "add" and not change.risky
    assert change.line() == "  + storage: provider r2"
    assert _only(added, "shop.Product.manual").line() == "  + shop.Product.manual: file:protected?"
    facts = json.loads(json.dumps(base.facts))
    facts["modules"].append(
        {"name": "storage", "settings": {"KARNI_STORAGE_PROVIDER": "aws"}, "defaults": {}}
    )
    report = validate_text(BASE)
    assert report.spec is not None
    plan = plan_project(report.spec, facts, base.root, file="karni.yaml")
    apply_counts(plan, lambda requests: {"rows": [3], "unreachable": {}})
    removed = _only(plan, "storage")
    assert removed.risky and removed.action == "remove" and removed.rows == 3


def test_counts_say_why_when_the_database_does_not_answer(
    base: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'gone.sqlite3'}")
    plan = _plan(_edit(("          note: text?\n", "")), base, counted=True)
    assert plan.row_counts == "unreachable"
    assert plan.note and "does not exist yet" in plan.note
    assert _only(plan, "shop.Product.note").rows is None
    assert "Row counts skipped: the database did not answer" in plan.text()
    assert not (tmp_path / "gone.sqlite3").exists()


# renames ------------------------------------------------------------------------------


def test_a_field_rename_with_was_keeps_the_column(base: Project) -> None:
    plan = _plan(
        _edit(('          sku: "str:20"\n', '          code: {type: "str:20", was: sku}\n')), base
    )
    change = _only(plan, "shop.Product.code")
    assert change.action == "rename" and not change.risky
    assert change.line() == "  ~ shop.Product.code: from sku"
    assert [c.target for c in plan.changes if c.area == "fields"] == ["shop.Product.code"]
    shorter = _plan(
        _edit(('          sku: "str:20"\n', '          code: {type: "str:8", was: sku}\n')), base
    )
    renamed = _only(shorter, "shop.Product.code")
    assert renamed.risky and renamed.detail == "from sku, str:20 -> str:8"


def test_without_was_a_removed_and_an_added_field_of_one_type_are_a_probable_rename(
    base: Project,
) -> None:
    plan = _plan(_edit(('          sku: "str:20"\n', '          code: "str:20"\n')), base)
    removed = _only(plan, "shop.Product.sku")
    assert removed.risky and removed.action == "remove"
    assert removed.reason == (
        'its values are lost, probably renamed to code: write code: {type: "str:20", was: sku} '
        "to keep them"
    )
    assert _only(plan, "shop.Product.code").action == "add"


def test_an_entity_rename_with_was_follows_its_relations(base: Project) -> None:
    plan = _plan(
        _edit(
            ("      Supplier:\n", "      Vendor:\n        was: Supplier\n"),
            ("          supplier: fk:Supplier?\n", "          supplier: fk:Vendor?\n"),
        ),
        base,
    )
    assert _only(plan, "shop.Vendor").line() == "  ~ shop.Vendor: from Supplier, rows kept"
    assert not plan.risky, plan.text()
    without = _plan(
        _edit(
            ("      Supplier:\n", "      Vendor:\n"),
            ("          supplier: fk:Supplier?\n", "          supplier: fk:Vendor?\n"),
        ),
        base,
    )
    assert _only(without, "shop.Supplier").risky
    assert _only(without, "shop.Order.supplier").reason == (
        "it points at shop.Vendor instead of shop.Supplier"
    )


def test_what_the_project_has_outside_the_spec_is_not_added_over(base: Project) -> None:
    facts = json.loads(json.dumps(base.facts))
    (shop,) = [a for a in facts["apps"] if a["label"] == "shop"]
    shop["models"].append(_model("shop.Legacy"))  # not on BaseModel: not an entity
    product = next(m for m in shop["models"] if m["name"] == "Product")
    product["fields"].append({**_model("x.Y")["fields"][0], "name": "barcode", "kwargs": {}})
    text = _edit(
        ("          kind: str:30?\n", '          kind: str:30?\n          barcode: "str:20"\n'),
        ("pages:\n", '      Legacy:\n        fields: {sku: "str:20"}\npages:\n'),
    )
    report = validate_text(text)
    assert report.spec is not None, report.issues
    plan = plan_project(report.spec, facts, base.root, file="karni.yaml")
    legacy, barcode = _only(plan, "shop.Legacy"), _only(plan, "shop.Product.barcode")
    assert legacy.risky and legacy.reason and "outside the spec" in legacy.reason
    assert barcode.risky and barcode.reason and "has this field already" in barcode.reason


# pk, external and database entities -----------------------------------------------------


def _model(label: str, **extra: Any) -> dict[str, Any]:
    fact = {
        "name": "sku",
        "class": "django.db.models.fields.CharField",
        "path": "django.db.models.CharField",
        "kwargs": {"max_length": 20},
        "null": False,
        "blank": False,
        "generated": False,
    }
    return {
        "name": label.split(".")[1],
        "label": label,
        "base_model": False,
        "pk": None,
        "managed": True,
        "db_table": label.replace(".", "_").lower(),
        "proxy": False,
        "fields": [fact],
        "ordering": [],
        "karni": {},
        "admin_meta": {},
        "api_meta": [],
        **extra,
    }


def _storage_facts(base: Project) -> dict[str, Any]:
    facts = json.loads(json.dumps(base.facts))
    facts["databases"] = ["default", "warehouse"]
    facts["apps"].append(
        {
            "label": "stock",
            "name": "stock",
            "models": [
                _model("stock.Part", base_model=True, pk="bigint"),
                _model(
                    "stock.Sale",
                    managed=False,
                    db_table='reporting"."sales',
                    karni={"external": True, "writable": True, "database": "warehouse"},
                ),
                _model("stock.Mapping", pk="uuid", karni={"database": "warehouse"}),
            ],
        }
    )
    return facts


STORAGE = """\
  stock:
    entities:
      Part: {fields: {sku: "str:20"}, pk: bigint, access: code}
      Sale:
        fields: {sku: "str:20"}
        external: true
        table: reporting.sales
        writable: true
        database: warehouse
        access: code
      Mapping: {fields: {sku: "str:20"}, database: warehouse, access: code}
"""


def test_pk_external_and_database_are_exported_and_plan_nothing(base: Project) -> None:
    facts = _storage_facts(base)
    exported = build(facts, base.root).data["apps"]["stock"]["entities"]
    assert exported["Part"] == {"fields": {"sku": "str:20"}, "pk": "bigint", "access": "code"}
    assert exported["Sale"] == {
        "fields": {"sku": "str:20"},
        "external": True,
        "table": "reporting.sales",
        "writable": True,
        "database": "warehouse",
        "access": "code",
    }
    assert exported["Mapping"]["database"] == "warehouse" and "pk" not in exported["Mapping"]
    text = BASE.replace("pages:\n", STORAGE + "pages:\n")
    report = validate_text(text, databases=facts["databases"])
    assert report.ok and report.spec is not None, report.issues
    assert plan_project(report.spec, facts, base.root, file="karni.yaml").changes == []


def test_pk_external_and_database_changes(base: Project) -> None:
    facts = _storage_facts(base)
    text = BASE.replace("pages:\n", STORAGE + "pages:\n")
    text = text.replace("pk: bigint, access: code", "pk: uuid, access: code")
    text = text.replace("        table: reporting.sales\n", "        table: reporting.sales_2026\n")
    text = text.replace('{sku: "str:20"}, database: warehouse', '{sku: "str:20"}')
    report = validate_text(text, databases=facts["databases"])
    assert report.spec is not None, report.issues
    plan = plan_project(report.spec, facts, base.root, file="karni.yaml")
    assert _only(plan, "stock.Part pk").risky
    table = _only(plan, "stock.Sale table")
    assert table.detail == "reporting.sales -> reporting.sales_2026" and not table.risky
    moved = _only(plan, "stock.Mapping database")
    assert (
        moved.risky and moved.reason == "the rows stay on warehouse, karni build does not move them"
    )
    added = _plan(
        BASE.replace(
            "pages:\n",
            "      Ledger:\n        fields: {code: str}\n        external: true\n"
            "        table: ledger\npages:\n",
        ),
        base,
    )
    assert _only(added, "shop.Ledger").detail == "(code str) external ledger"
    gone = BASE.replace(
        "pages:\n",
        "  stock:\n    entities:\n      Part: {pk: bigint, access: code}\n"
        "      Sale: {external: true, table: reporting.sales, writable: true, "
        "database: warehouse, access: code}\npages:\n",
    )
    report = validate_text(gone, databases=facts["databases"])
    assert report.spec is not None, report.issues
    removed = plan_project(report.spec, facts, base.root, file="karni.yaml")
    sale_field = _only(removed, "stock.Sale.sku")  # an external table keeps its columns
    assert not sale_field.risky and sale_field.reason == "its column stays"
    assert _only(removed, "stock.Mapping").risky  # a table Karni manages is dropped
    assert _only(removed, "stock.Part.sku").risky


# trees -------------------------------------------------------------------------------------


def _tree_facts(base: Project) -> dict[str, Any]:
    facts = json.loads(json.dumps(base.facts))
    facts["apps"].append(
        {
            "label": "geo",
            "name": "geo",
            "models": [
                _model("geo.Region", base_model=True, pk="uuid", tree="tree"),
                _model("geo.Category", base_model=True, pk="uuid", tree="ordered"),
                _model("geo.Zone", base_model=True, pk="uuid", tree=None),
            ],
        }
    )
    return facts


TREES = """\
  geo:
    entities:
      Region: {fields: {sku: "str:20"}, access: code, tree: true}
      Category: {fields: {sku: "str:20"}, access: code, tree: ordered, order: [position]}
      Zone: {fields: {sku: "str:20"}, access: code}
"""


def _tree_plan(base: Project, text: str) -> Plan:
    facts = _tree_facts(base)
    facts["apps"][-1]["models"][1]["ordering"] = ["position"]
    report = validate_text(BASE.replace("pages:\n", text + "pages:\n"))
    assert report.ok and report.spec is not None, report.issues
    return plan_project(report.spec, facts, base.root, file="karni.yaml")


def test_a_tree_is_exported_and_plans_nothing(base: Project) -> None:
    exported = build(_tree_facts(base), base.root).data["apps"]["geo"]["entities"]
    assert exported["Region"]["tree"] is True and exported["Category"]["tree"] == "ordered"
    assert "tree" not in exported["Zone"]
    assert _tree_plan(base, TREES).changes == []


def test_a_change_between_flat_and_tree_is_risky(base: Project) -> None:
    text = """\
  geo:
    entities:
      Region: {fields: {sku: "str:20"}, access: code}
      Category: {fields: {sku: "str:20"}, access: code, tree: true}
      Zone: {fields: {sku: "str:20"}, access: code, tree: true}
"""
    plan = _tree_plan(base, text)
    flat = _only(plan, "geo.Region tree")
    assert flat.detail == "true -> false" and flat.risky
    assert flat.reason == "the parent column is dropped, and every row's place in the tree with it"
    assert [count.request() for count in flat.counts] == [
        {"model": "geo.Region", "field": "parent", "kind": "set"}
    ]
    unordered = _only(plan, "geo.Category tree")
    assert unordered.detail == "ordered -> true" and unordered.risky
    made = _only(plan, "geo.Zone tree")
    assert made.detail == "false -> true" and made.risky
    assert made.reason is not None and made.reason.startswith("every row becomes a root")
    assert [c.target for c in plan.changes if c.area == "migrations"] == ["geo"]
    ordered = _tree_plan(base, TREES.replace("tree: true}", "tree: ordered}"))
    added = _only(ordered, "geo.Region tree")
    assert added.detail == "true -> ordered" and not added.risky  # a position column is added
    new = _tree_plan(base, TREES + "      Area: {fields: {name: str}, tree: ordered}\n")
    assert _only(new, "geo.Area").detail == "(name str) tree ordered"


def test_a_tree_scope_grant_is_planned_and_checked(base: Project) -> None:
    store = TREES + "      Store: {fields: {region: fk:Region}, access: code}\n"
    member = "  member: {name: Member, default: true, grants: {shop.order: own}}\n"

    def planned(scope: str) -> Plan:
        grant = member.replace("shop.order: own}", f"shop.order: own, geo.store:view: '{scope}'}}")
        text = BASE.replace(member, grant).replace("pages:\n", store + "pages:\n")
        report = validate_text(text)
        assert report.ok and report.spec is not None, report.issues
        return plan_project(report.spec, _tree_facts(base), base.root, file="karni.yaml")

    added = _only(planned("tree:region"), "member grant geo.store:view")
    assert (added.action, added.detail, added.risky) == ("add", "tree:region", False)
    assert "  + member grant geo.store:view: tree:region" in planned("tree:region").text()
    bad = validate_text(
        BASE.replace(member, member.replace("own}", "own, geo.store:view: 'tree:sku'}")).replace(
            "pages:\n", store + "pages:\n"
        )
    )
    assert [issue.code for issue in bad.issues] == ["C620"]


def _tagged_facts(base: Project, taxonomies: dict[str, dict[str, Any]]) -> dict[str, Any]:
    facts = _tree_facts(base)
    facts["apps"][-1]["models"][1]["ordering"] = ["position"]
    facts["apps"][-1]["models"].append(
        _model("geo.Store", base_model=True, pk="uuid", taxonomies=taxonomies)
    )
    return facts


def _tagged_plan(base: Project, facts: dict[str, Any], store: str) -> Plan:
    text = BASE.replace("pages:\n", TREES + store + "pages:\n")
    report = validate_text(text)
    assert report.ok and report.spec is not None, report.issues
    return plan_project(report.spec, facts, base.root, file="karni.yaml")


def test_taxonomies_are_exported_and_planned(base: Project) -> None:
    tagged = {
        "region": {"to": "geo.Region", "generated": True},
        "category": {"to": "geo.Category", "generated": True},
    }
    facts = _tagged_facts(base, tagged)
    exported = build(facts, base.root).data["apps"]["geo"]["entities"]["Store"]
    assert exported["taxonomies"] == {"region": "geo.Region", "category": "geo.Category"}
    assert exported["fields"] == {"sku": "str:20"}
    same = "      Store:\n        fields: {sku: 'str:20'}\n        access: code\n"
    both = same + "        taxonomies: {region: Region, category: geo.Category}\n"
    assert _tagged_plan(base, facts, both).changes == []
    # one taxonomy added: a migration adds its table, nothing is lost
    plan = _tagged_plan(base, _tagged_facts(base, {"region": tagged["region"]}), both)
    added = _only(plan, "geo.Store taxonomies")
    assert added.detail == "region geo.Region -> category geo.Category, region geo.Region"
    assert not added.risky
    assert [c.target for c in plan.changes if c.area == "migrations"] == ["geo"]
    # one removed: its tags go with its table
    removed = _only(
        _tagged_plan(base, facts, same + "        taxonomies: {region: Region}\n"),
        "geo.Store taxonomies",
    )
    assert (
        removed.risky and removed.reason == "the tags under category are dropped with their table"
    )
    new = _tagged_plan(
        base,
        _tree_facts(base),
        "      Shop: {fields: {name: str}, taxonomies: {region: Region}}\n",
    )
    assert _only(new, "geo.Shop").detail == "(name str) taxonomies region geo.Region"


def test_database_must_be_an_alias_the_project_has(
    base: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(base.root)
    spec = base.root / "warehouse.yaml"
    spec.write_text(
        BASE.replace(
            "pages:\n",
            "      Ledger:\n        fields: {code: str}\n        database: warehouse\npages:\n",
        )
    )
    try:
        result = CliRunner().invoke(app, ["plan", "--spec", str(spec), "--no-docker", "--json"])
    finally:
        spec.unlink()
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["valid"] is False and payload["changes"] == []
    assert [issue["code"] for issue in payload["issues"]] == ["C252"]
    assert "aliases: default" in payload["issues"][0]["message"]


# the command ------------------------------------------------------------------------------


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_plan_writes_nothing(base: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    """Files and database are byte for byte the same after a plan that counts rows."""
    monkeypatch.chdir(base.root)
    (base.root / "karni.yaml").write_text(_edit(("          note: text?\n", "")))
    try:
        files = _tree(base.root)
        database = hashlib.sha256(base.database.read_bytes()).hexdigest()
        result = CliRunner().invoke(app, ["plan", "--no-docker"])
        assert result.exit_code == 0, result.output
        assert "! - shop.Product.note: text?, its values are lost (2 rows)" in result.output
        assert _tree(base.root) == files
        assert hashlib.sha256(base.database.read_bytes()).hexdigest() == database
    finally:
        (base.root / "karni.yaml").unlink()


def test_an_invalid_spec_passes_the_validators_errors_through(
    base: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(base.root)
    runner = CliRunner()
    missing = runner.invoke(app, ["plan", "--no-docker"])
    assert missing.exit_code == 1 and "C210" in str(missing.exception)
    bad = base.root / "bad.yaml"
    bad.write_text(BASE.replace("fk:Product", "fk:Prodct"))
    try:
        text = runner.invoke(app, ["plan", "--spec", str(bad), "--no-docker"])
        assert text.exit_code == 1
        assert ": C230: Order.product points at Prodct" in text.output
        assert text.output.rstrip().endswith("1 problem, so no plan.")
        payload = json.loads(runner.invoke(app, ["plan", "--spec", str(bad), "--json"]).output)
        assert payload["valid"] is False and payload["issues"][0]["code"] == "C230"
    finally:
        bad.unlink()


def test_a_project_that_cannot_be_read_is_c250(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _env(monkeypatch, tmp_path / "db.sqlite3")
    root = _render(tmp_path, "Broken Facts")
    (root / "config" / "settings.py").write_text("raise RuntimeError('broken settings')\n")
    (root / "karni.yaml").write_text(FIXTURE.read_text())
    monkeypatch.chdir(root)
    result = CliRunner().invoke(app, ["plan", "--no-docker"])
    assert result.exit_code == 1 and "C250" in str(result.exception)
    assert "karni plan cannot read the project" in str(result.exception)


# the fixture on an empty project: snapshot, schema, tokens --------------------------------


@pytest.fixture(scope="module")
def empty(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, dict[str, Any]]]:
    """``karni plan`` and ``karni plan --json`` of the fixture on a fresh project."""
    parent = tmp_path_factory.mktemp("plan-empty")
    with pytest.MonkeyPatch.context() as mp:
        _env(mp, parent / "db.sqlite3")
        root = _render(parent, "Harbour Yoga")
        (root / "karni.yaml").write_text(FIXTURE.read_text())
        mp.chdir(root)
        runner = CliRunner()
        text = runner.invoke(app, ["plan", "--no-docker"])
        data = runner.invoke(app, ["plan", "--no-docker", "--json"])
        assert text.exit_code == 0 and data.exit_code == 0, text.output + data.output
        yield text.output, json.loads(data.output)


def test_an_empty_project_plans_everything(empty: tuple[str, dict[str, Any]]) -> None:
    text, data = empty
    areas = {change["area"] for change in data["changes"]}
    assert areas == set(plan_mod.AREAS) - {"fields"}  # a new entity's fields are on its line
    assert (
        "  + classes.Studio: (name str:120, slug slug:name, address text?) key slug, search name"
        in text
    )
    assert "  + payments: provider stripe" in text and "  + site" in text
    assert "  - user" in text and "  + member: default, grants classes.booking own" in text
    assert data["summary"] == {"changes": len(data["changes"]), "risky": 0, "not_managed": 0}
    assert data["row_counts"] == {"status": "not needed", "note": None}


def test_the_json_snapshot_of_the_fixture(empty: tuple[str, dict[str, Any]]) -> None:
    _text, data = empty
    rendered = json.dumps(data, indent=2) + "\n"
    if os.environ.get("KARNI_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(rendered)
    assert SNAPSHOT.read_text() == rendered, (
        "The fixture's plan changed. Check the difference, then rewrite the snapshot: "
        "KARNI_UPDATE_SNAPSHOTS=1 pytest tests/test_plan.py"
    )


def test_the_published_plan_schema_is_current_and_checks_the_output(
    empty: tuple[str, dict[str, Any]],
) -> None:
    expected = json.dumps(plan_mod.json_schema(), indent=2) + "\n"
    assert PLAN_SCHEMA.read_text() == expected, (
        "docs/assets/karni-plan.schema.json is stale. Regenerate it: "
        "python -m karni_cli.spec.plan > docs/assets/karni-plan.schema.json"
    )
    jsonschema = pytest.importorskip("jsonschema")
    published = json.loads(PLAN_SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(published)
    validator = jsonschema.Draft202012Validator(published)
    assert not list(validator.iter_errors(empty[1]))
    invalid = plan_mod.invalid_output("x.yaml", [])
    assert not list(validator.iter_errors(invalid))
    assert list(validator.iter_errors({**empty[1], "version": 2}))


def test_the_fixture_plan_fits_the_token_budget(empty: tuple[str, dict[str, Any]]) -> None:
    text = empty[0]
    assert len(text) / 4 < TOKEN_BUDGET
    tiktoken = pytest.importorskip("tiktoken")
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - encodings download on first use
        pytest.skip("tiktoken encodings unavailable offline")
    assert len(encoding.encode(text)) < TOKEN_BUDGET


# seed volumes (experimental)


def test_a_large_seed_count_shows_its_volume_and_time_class(base: Project) -> None:
    assert base.facts["seed_bulk_threshold"] == 1000
    plan = _plan(_edit(("seed: {Product: 5}", "seed: {Product: 500000, Supplier: 999}")), base)
    lines = plan.text().splitlines()
    assert "  ~ Product: 5 -> 500000, 500,000 rows in bulk, minutes" in lines
    assert "  + Supplier: 999" in lines  # under the threshold: the demo path, no note
    change = next(c for c in plan.changes if c.area == "seed" and c.target == "Product")
    assert change.as_dict()["reason"] == "500,000 rows in bulk, minutes" and not change.risky
    facts = {**base.facts, "seed_bulk_threshold": 100}
    report = validate_text(_edit(("seed: {Product: 5}", "seed: {Product: 150}")))
    assert report.spec is not None
    moved = plan_project(report.spec, facts, base.root, file="karni.yaml")
    assert any(c.reason == "150 rows in bulk, seconds" for c in moved.changes)


def test_the_time_classes_match_the_seeder() -> None:
    import pytest

    from karni_cli.spec.plan import SEED_BULK_THRESHOLD, SEED_ROWS_PER_SECOND, seed_time_class

    bulk = pytest.importorskip("karni.bulk_seeding")
    assert SEED_BULK_THRESHOLD == bulk.BULK_THRESHOLD
    assert SEED_ROWS_PER_SECOND == bulk.ROWS_PER_SECOND
    for rows in (10, 50_000, 300_000, 1_000_000, 10_000_000):
        assert seed_time_class(rows) == bulk.time_class(rows)
