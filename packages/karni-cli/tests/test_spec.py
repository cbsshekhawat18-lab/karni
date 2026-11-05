"""``karni spec`` (experimental): the karni.yaml format, validation, the JSON Schema and export.

The export of both examples and the round trip (a project built with
``karni make`` from a spec's entities, exported and compared with the spec)
run the project's ``manage.py karni_facts`` through this interpreter.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli.builder.render import _search_option
from karni_cli.errorcodes import CODES
from karni_cli.generators.naming import default_route
from karni_cli.main import app
from karni_cli.settings_edit import add_app
from karni_cli.spec import catalog, emit, schema
from karni_cli.spec.export import build, export_project
from karni_cli.spec.normal import canonical_field, normalise
from karni_cli.spec.validate import Report, iter_codes, validate_text

from .conftest import REPO_ROOT, TEMPLATE, require_modules

FIXTURE = Path(__file__).parent / "fixtures" / "spec" / "harbour-yoga.yaml"
SCHEMA_FILE = REPO_ROOT / "docs" / "assets" / "karni-spec.schema.json"
DOCS = REPO_ROOT / "docs" / "app-spec.md"


def check(text: str) -> Report:
    return validate_text(textwrap.dedent(text))


def codes(text: str) -> list[tuple[str, int | None]]:
    return [(issue.code, issue.line) for issue in check(text).issues]


# valid specs ----------------------------------------------------------------------


def test_the_example_spec_is_valid() -> None:
    report = validate_text(FIXTURE.read_text())
    assert report.ok, [issue.render("x") for issue in report.issues]
    assert report.spec is not None
    session = report.spec.apps["classes"].entities["Session"]
    assert session.owner == "instructor" and session.order == ["starts_at"]
    assert (
        report.spec.features.terms is not None and report.spec.features.terms.version == "2026-11"
    )


def test_the_docs_example_is_the_fixture_and_valid() -> None:
    text = DOCS.read_text()
    block = text.split("```yaml\n", 1)[1].split("```", 1)[0]
    assert block == FIXTURE.read_text()


def test_a_minimal_spec_and_its_defaults() -> None:
    report = check("version: 1\napp: {name: Shop}\n")
    assert report.ok and report.spec is not None
    assert report.spec.app.kind == "app"
    data = normalise(report.spec)
    assert data["features"] == {
        "two_factor": False,
        "email_code_login": False,
        "social_login": [],
        "terms": None,
        "user_grants": False,
        "api_cache": False,
    }


def test_x_keys_are_kept_and_ignored_everywhere() -> None:
    report = check(
        """\
        version: 1
        x-top: 1
        app: {name: Shop, x-why: notes}
        roles:
          staff: {x-note: hi, grants: {"*": all, x-later: own}}
        apps:
          shop:
            x-owner: team a
            entities:
              x-draft: {anything: goes}
              Product:
                x-comment: [1, 2]
                fields: {name: str, x-maybe: "int"}
                access: {read: public, x-todo: tighten}
        pages:
          - Product: list
        """
    )
    assert report.ok, report.issues
    assert report.spec is not None
    assert list(report.spec.apps["shop"].entities) == ["Product"]
    assert list(report.spec.apps["shop"].entities["Product"].fields) == ["name"]
    assert "x-top" in report.source.data  # type: ignore[union-attr]


# every code, with its line ---------------------------------------------------------

HEAD = "version: 1\napp: {name: Shop}\n"
SHOP = HEAD + "apps:\n  shop:\n    entities:\n      Product:\n"
#: A product on a category tree, a listing on a product and a flat tag (the tree scope).
TREES = (
    SHOP
    + "        fields: {category: fk:Category, tags: 'm2m:Tag?'}\n"
    + "      Category: {fields: {name: str}, tree: true}\n"
    + "      Tag: {fields: {name: str}}\n"
    + "      Listing: {fields: {product: fk:Product}}\n"
    + "roles:\n  buyer:\n    grants:\n"
)
NAV = SHOP + "        fields: {name: str}\npages:\n  - home: dashboard\n  - Product: list\n"


def tagged(taxonomies: str) -> str:
    """A product with ``taxonomies``, a category tree and flat tags."""
    return (
        SHOP
        + "        fields: {name: str, tags: 'm2m:Tag?'}\n"
        + f"        taxonomies: {taxonomies}\n"
        + "      Category: {fields: {name: str}, tree: true}\n"
        + "      Tag: {fields: {name: str}}\n"
    )


INVALID: list[tuple[str, str, int | None]] = [
    ("C211", "version: 1\napp: [unclosed\n", 3),
    ("C212", HEAD + "colour: blue\n", 3),
    ("C212", SHOP + "        fields: {name: str}\n        serch: [name]\n", 8),
    ("C213", "app: {name: Shop}\n", 1),
    ("C213", HEAD + "features: {two_factor: maybe}\n", 3),
    ("C213", "- a list\n", 1),
    ("C214", "version: 2\napp: {name: Shop}\n", 1),
    ("C215", HEAD + "apps:\n  Shop: {}\n", 4),
    ("C215", HEAD + "apps:\n  shop:\n    entities:\n      product: {}\n", 6),
    ("C216", SHOP + "        fields: {name: 'strr:80'}\n", 7),
    ("C216", SHOP + "        fields: {slug: 'slug:title'}\n", 7),
    ("C216", SHOP + "        fields: {price: 'decimal:4:6'}\n", 7),
    ("C217", SHOP + "        access: {read: everyone}\n", 7),
    ("C218", HEAD + "roles:\n  staff: {grants: {'*': most}}\n", 4),
    ("C218", HEAD + "roles:\n  staff: {grants: {'shop': all}}\n", 4),
    ("C219", HEAD + "features: {social_login: [myspace]}\n", 3),
    ("C220", SHOP + "        fields: {name: str}\npages:\n  - Product: [list, table]\n", 9),
    ("C221", HEAD + "modules: {payments: {colour: red}}\n", 3),
    ("C221", HEAD + "modules: {payments: {provider: 3}}\n", 3),
    ("C222", HEAD + "roles:\n  staff: {}\n  staff: {}\n", 5),
    ("C223", SHOP + "        fields: {name: str}\nseed: {Product: -1}\n", 8),
    ("C224", SHOP + "        fields: {body: markdown}\n", 7),
    ("C225", HEAD + "modules: {site: {}}\n", 3),
    ("C230", SHOP + "        fields: {maker: fk:Maker}\n", 7),
    ("C231", HEAD + "apps:\n  a: {entities: {Tag: {}, Post: {fields: {tag: fk:b.Tag}}}}\n"
     "  b: {entities: {Tag: {}}}\n  c: {entities: {Note: {fields: {tag: fk:Tag}}}}\n", 6),
    ("C232", SHOP + "        access: {write: 'role:editor'}\n", 7),
    ("C233", HEAD + "roles:\n  staff: {grants: {shop.product: all}}\n", 4),
    ("C234", SHOP + "        fields: {maker: fk:User}\nroles:\n  m: {grants: {shop.product: own:maker}}\n", 9),
    ("C235", HEAD + "pages:\n  - Product: list\n", 4),
    ("C236", HEAD + "modules: {chat: {}}\n", 3),
    ("C237", SHOP + "        fields: {name: str}\n        groups: {Main: [name, price]}\n", 8),
    ("C238", SHOP + "        fields: {name: str}\n        key: sku\n", 8),
    ("C239", SHOP + "        fields: {name: str}\n        owner: name\n", 8),
    ("C240", SHOP + "        fields: {name: str}\n        access: {read: 'owned:name'}\n", 8),
    ("C241", HEAD + "seed: {Product: 3}\n", 3),
    ("C242", SHOP + "        fields: {name: str}\npages:\n  - Product: list\n  - products: blank\n", 10),
    ("C251", SHOP + "        external: true\n", 7),
    ("C251", SHOP + "        table: sales\n", 7),
    ("C251", SHOP + "        external: true\n        table: sales\n        pk: bigint\n", 9),
    ("C251", SHOP + "        external: true\n        table: 'a.b.c'\n", 8),
    ("C251", SHOP + "        {external: true, table: sales}\nseed: {Product: 5}\n", 8),
    ("C252", SHOP + "        database: 'two words'\n", 7),
    ("C253", HEAD + "apps:\n  shop:\n    entities:\n      Stock: {database: warehouse}\n"
     "      Item: {fields: {stock: fk:Stock}}\n", 7),
    ("C253", SHOP + "        fields: {buyer: fk:User}\n        database: warehouse\n", 7),
    ("C254", SHOP + "        was: Product\n", 7),
    ("C254", SHOP + "        fields: {title: {type: str, was: name}, name: str}\n", 7),
    ("C254", SHOP + "        fields: {a: {type: str, was: x}, b: {type: str, was: x}}\n", 7),
    ("C460", SHOP + "        {external: true, table: sales, tree: true}\n", 7),
    ("C460", SHOP + "        fields: {name: str, parent: 'fk:Product?'}\n        tree: true\n", 7),
    ("C460", SHOP + "        fields: {position: int}\n        tree: ordered\n", 7),
    ("C620", TREES + "      shop.product:view: 'tree:tags'\n", 14),
    ("C620", TREES + "      shop.product:view: 'tree:name'\n", 14),
    ("C620", TREES + "      shop.listing:view: 'tree:product'\n", 14),
    ("C620", TREES + "      shop.listing:view: 'tree:product__Category'\n", 14),
    ("C620", TREES + "      shop.tag:*: 'tree:category'\n", 14),
    ("C620", TREES + "      shop.*: 'tree:region'\n", 14),
    ("C640", NAV + "navigation: [home, Products]\n", 11),
    ("C640", SHOP + "        fields: {name: str}\npages:\n  - Product: [detail]\nnavigation: [Product]\n", 10),
    ("C641", NAV + "navigation:\n  - Catalog: []\n", 12),
    ("C641", NAV + "navigation:\n  - Product: {icon: Big Box}\n", 12),
    ("C641", NAV + "navigation:\n  - home\n  - Catalog: [Product, home]\n", 13),
    ("C641", NAV + "navigation:\n  - Product: [home]\n", 12),
    ("C641", NAV + "navigation:\n  - {Catalog: [Product], Other: [home]}\n", 12),
    ("C642", NAV + "navigation:\n  - Product: {requires: staff}\n", 12),
    ("C642", NAV + "navigation:\n  - Product: {requires: 'shop.prodct:view'}\n", 12),
    ("C700", tagged("{region_descendants: Category}"), 8),
    ("C700", tagged("{created_by: Category}"), 8),
    ("C700", tagged("{Region: Category}"), 8),
    ("C701", tagged("{tag: Tag}"), 8),
    ("C230", tagged("{area: Area}"), 8),
    ("C702", tagged("{tags: Category}"), 8),
    ("C702", tagged("{name: Category}"), 8),
    ("C703", SHOP + "        {external: true, table: sales, taxonomies: {category: Category}}\n"
     "      Category: {fields: {name: str}, tree: true}\n", 7),
    ("C500", SHOP + "        fields: {name: str}\n        aggregate: {group_by: [colour]}\n", 8),
    ("C500", SHOP + "        fields: {name: str}\n        aggregate: {group_by: [name__x]}\n", 8),
    ("C500", SHOP + "        fields: {name: str}\n        aggregate: {group_by: []}\n", 8),
    ("C500", SHOP + "        fields: {name: str}\n        aggregate:\n          group_by: name\n"
     "          values: [weight]\n", 10),
    ("C501", SHOP + "        fields: {name: str}\n        aggregate: {group_by: name, metrics: [median]}\n",
     8),
    ("C502", SHOP + "        fields: {name: str}\n        aggregate: {group_by: ['name:year']}\n", 8),
    ("C502", SHOP + "        fields: {on: date}\n        aggregate: {group_by: ['on:week']}\n", 8),
    ("C213", HEAD + "features: {api_cache: 60}\n", 3),
    ("C213", SHOP + "        cache: soon\n", 7),
    ("C219", HEAD + "features:\n  api_cache: {ttl: 0}\n", 4),
    ("C520", SHOP + "        cache: true\n", 7),
    ("C520", SHOP + "        cache: -5\n", 7),
    ("C521", HEAD + "features: {api_cache: true}\napps:\n  shop:\n    entities:\n"
     "      Sale: {external: true, table: sales}\n", 7),
    ("C521", HEAD + "features: {api_cache: true}\napps:\n  shop:\n    entities:\n"
     "      Stock: {database: warehouse}\n", 7),
    ("C521", HEAD + "features: {api_cache: true}\napps:\n  shop:\n    entities:\n"
     "      Sale: {external: true, table: sales, cache: 30}\n"
     "      Line: {fields: {sale: fk:Sale}}\n", 8),
    ("C213", SHOP + "        fields: {name: str}\n        global_search: {weight: 0}\n", 8),
    ("C540", SHOP + "        fields: {name: str, stock: int}\n"
     "        global_search: {fields: [stock]}\n", 8),
    ("C540", SHOP + "        fields: {name: str, maker: fk:User}\n        search: [maker__email]\n"
     "        global_search: true\n", 9),
    ("C541", SHOP + "        fields: {name: str}\n        global_search: true\n", 8),
    ("C542", SHOP + "        fields: {name: str}\n"
     "        global_search: {fields: [name], subtitle: maker__name}\n", 8),
    ("C542", SHOP + "        fields: {name: str, sku: str}\n"
     "        global_search: {fields: [name], title: sku__code}\n", 8),
]  # fmt: skip


@pytest.mark.parametrize(("code", "text", "line"), INVALID)
def test_each_problem_has_its_code_and_line(code: str, text: str, line: int | None) -> None:
    found = [(issue.code, issue.line) for issue in validate_text(text).issues]
    assert (code, line) in found, found


def test_every_code_is_tested_and_registered() -> None:
    # C324 needs a manifest that requires or conflicts with another: tests/test_catalog.py.
    tested = {code for code, _, _ in INVALID} | {"C324"}
    assert set(iter_codes()) == tested
    registered = {entry.code for entry in CODES}
    assert {*iter_codes(), "C210", "C245", "C246"} <= registered
    # The spec's own codes, C324 (the module catalog's requires and conflicts), the trees' C460-C479,
    # the aggregations' C500-C519, response caching's C520-C539, the tree scope's C620-C639,
    # navigation's C640-C659, the taxonomies' C700-C719 and global_search's C540-C559.
    assert all(
        200 <= int(code[1:]) <= 269
        or code == "C324"
        or 460 <= int(code[1:]) <= 479
        or 500 <= int(code[1:]) <= 559
        or 620 <= int(code[1:]) <= 639
        or 640 <= int(code[1:]) <= 659
        or 700 <= int(code[1:]) <= 719
        for code in iter_codes()
    )


def test_issues_name_the_fix_and_the_path() -> None:
    (issue,) = check(
        """\
        version: 1
        app: {name: Shop}
        apps:
          shop:
            entities:
              Order:
                fields:
                  buyer: fk:Customer
        """
    ).issues
    assert issue.code == "C230" and issue.line == 8
    assert issue.path == "apps.shop.entities.Order.fields.buyer"
    assert "Customer" in issue.message and issue.fix


def test_field_errors_are_the_generators_own() -> None:
    (issue,) = check(SHOP + "        fields: {status: 'choice:'}\n").issues
    assert issue.code == "C216"
    assert "choice needs values" in issue.message and "C104" in issue.message


def test_relations_reach_users_modules_and_other_apps() -> None:
    report = check(
        """\
        version: 1
        app: {name: Shop}
        modules: {payments: {}}
        apps:
          shop:
            entities:
              Order:
                fields: {buyer: fk:User, paid: "fk:karni_payments.Payment?", tag: "m2m:blog.Tag?"}
                owner: buyer
                access: {read: [owned:buyer, "role:staff"], write: owned:buyer}
          blog:
            entities:
              Tag: {fields: {parent: "fk:self?"}}
        roles:
          staff: {grants: {"*": all, karni_payments.payment: all, shop.order:view: own}}
        """
    )
    assert report.ok, report.issues


def test_a_tree_entity_its_fields_and_its_normal_form() -> None:
    report = check(
        """\
        version: 1
        app: {name: Shop}
        apps:
          shop:
            entities:
              Region: {fields: {name: str}, tree: true, search: [name, parent__name]}
              Category:
                fields: {name: str}
                tree: ordered
                order: [position]
                groups: {Main: [name, parent, position]}
              Product: {fields: {category: fk:Category, regions: "m2m:Region?"}}
        """
    )
    assert report.ok, report.issues
    assert report.spec is not None
    entities = normalise(report.spec)["apps"]["shop"]["entities"]
    assert entities["Region"]["tree"] is True and entities["Category"]["tree"] == "ordered"
    assert entities["Product"]["tree"] is False
    # position belongs to an ordered tree only
    found = codes(
        SHOP + "        fields: {name: str}\n        tree: true\n        order: [position]\n"
    )
    assert [code for code, _line in found] == ["C238"]


def test_a_tree_scope_follows_relations_to_a_tree_entity() -> None:
    text = (
        TREES
        + "      shop.product:view: 'tree:category'\n"
        + "      shop.listing:*: 'tree:product__category'\n"
        + "      shop.*:view: 'tree:category'\n"
        + "      '*': 'tree:product__category'\n"
    )
    report = check(text)
    assert report.ok, [issue.render("x") for issue in report.issues]
    assert report.spec is not None
    grants = normalise(report.spec)["roles"]["buyer"]["grants"]
    assert grants["shop.product:view"] == "tree:category"
    assert grants["shop.listing:*"] == "tree:product__category"
    (issue,) = check(TREES + "      shop.listing:view: 'tree:product'\n").issues
    assert "'product' does not lead from Listing to an entity with tree: true" in issue.message


def test_taxonomies_point_at_tree_entities_and_normalise_to_labels() -> None:
    text = (
        SHOP
        + "        fields: {name: str, region: 'm2m:geo.Region?'}\n"
        + "        taxonomies: {region: geo.Region, category: Category}\n"
        + "      Category: {fields: {name: str}, tree: ordered}\n"
        + "  geo:\n    entities:\n      Region: {fields: {name: str}, tree: true}\n"
        + "roles:\n  buyer:\n    grants:\n"
        + "      shop.product:view: 'tree:category'\n"
        + "      shop.product:change: 'tree:region'\n"
    )
    report = check(text)
    assert report.ok, [issue.render("x") for issue in report.issues]
    assert report.spec is not None
    product = normalise(report.spec)["apps"]["shop"]["entities"]["Product"]
    assert product["taxonomies"] == {"category": "shop.Category", "region": "geo.Region"}
    # the adopted field must point at the same tree
    found = check(text.replace("'m2m:geo.Region?'", "'m2m:Category?'")).issues
    assert [issue.code for issue in found] == ["C702"]
    assert "adopts the field Product.region, which is not an m2m to Region" in found[0].message
    (issue,) = check(tagged("{tag: Tag}")).issues
    assert "points at Tag, which is not an entity with tree: true" in issue.message


def test_a_tree_value_names_the_values_it_takes() -> None:
    (issue,) = check(SHOP + "        tree: yes please\n").issues
    assert issue.code == "C213" and issue.line == 7
    assert "must be true, false or ordered, got a string ('yes please')" in issue.message


def test_an_aggregate_with_paths_buckets_and_metrics() -> None:
    report = check(
        """\
        version: 1
        app: {name: Shop}
        apps:
          shop:
            entities:
              Category: {fields: {name: str, parent: "fk:self?"}}
              Product:
                fields:
                  category: fk:Category
                  channel: "choice:online|store"
                  launched_on: date
                  price: "money:EUR"
                  buyer: "fk:User?"
                aggregate:
                  group_by: [category, category__parent, category__name, channel,
                             "launched_on:year", launched_on, created_at, buyer__email]
                  values: [price, category]
                  metrics: [count, sum]
        """
    )
    assert report.ok, report.issues
    assert report.spec is not None
    declared = report.spec.apps["shop"].entities["Product"].aggregate
    assert declared is not None and declared.metrics == ["count", "sum"]
    data = normalise(report.spec)["apps"]["shop"]["entities"]["Product"]["aggregate"]
    assert data["group_by"][0] == "category" and data["metrics"] == ["count", "sum"]
    shorthand = check(SHOP + "        fields: {name: str}\n        aggregate: {group_by: name}\n")
    assert shorthand.ok and shorthand.spec is not None
    every = normalise(shorthand.spec)["apps"]["shop"]["entities"]["Product"]["aggregate"]
    assert every == {
        "group_by": ["name"],
        "values": [],
        "metrics": sorted(schema.AGGREGATE_METRICS),
    }


def test_the_spec_metrics_and_buckets_are_cores() -> None:
    aggregation = pytest.importorskip("karni.aggregation")
    assert schema.AGGREGATE_METRICS == aggregation.METRICS
    assert schema.AGGREGATE_BUCKETS == aggregation.BUCKETS


def test_owner_paths_through_relations() -> None:
    base = SHOP.replace("Product:\n", "Workspace: {fields: {members: m2m:User}}\n      Lead:\n")
    assert check(base + "        fields: {ws: fk:Workspace}\n        owner: ws__members\n").ok
    found = codes(base + "        fields: {ws: fk:Workspace}\n        owner: ws__name\n")
    assert found and found[0][0] == "C239"


# the JSON Schema ------------------------------------------------------------------


def test_the_published_json_schema_is_current() -> None:
    expected = json.dumps(schema.json_schema(), indent=2) + "\n"
    assert SCHEMA_FILE.read_text() == expected, (
        "docs/assets/karni-spec.schema.json is stale. Regenerate it: "
        "python -m karni_cli.spec.schema > docs/assets/karni-spec.schema.json"
    )


def test_the_json_schema_agrees_with_the_validator() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    published = json.loads(SCHEMA_FILE.read_text())
    jsonschema.Draft202012Validator.check_schema(published)
    validator = jsonschema.Draft202012Validator(published)
    assert not list(validator.iter_errors(yaml.safe_load(FIXTURE.read_text())))
    for text in (HEAD + "colour: blue\n", SHOP + "        serch: [x]\n", "app: {name: x}\n"):
        assert list(validator.iter_errors(yaml.safe_load(text))), text
        assert not validate_text(text).ok
    menu = NAV + "navigation:\n  - home\n  - Catalog: {icon: box, items: [Product]}\n"
    assert not list(validator.iter_errors(yaml.safe_load(menu))) and validate_text(menu).ok
    two_keys = NAV + "navigation:\n  - {Catalog: [Product], Other: [home]}\n"
    assert list(validator.iter_errors(yaml.safe_load(two_keys)))


def test_export_writes_the_schema_line_first() -> None:
    exported = build(_facts(), REPO_ROOT / "examples" / "eventhub")
    first = exported.text().splitlines()[0]
    assert first == f"# yaml-language-server: $schema={schema.SCHEMA_URL}"


# the command ----------------------------------------------------------------------


def test_validate_command_text_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    missing = runner.invoke(app, ["spec", "validate"])
    assert missing.exit_code == 1 and "C210" in str(missing.exception)
    (tmp_path / "karni.yaml").write_text(FIXTURE.read_text())
    good = runner.invoke(app, ["spec", "validate"])
    assert good.exit_code == 0, good.output
    assert "karni.yaml: valid (1 app(s), 3 entities" in good.output
    (tmp_path / "bad.yaml").write_text(SHOP + "        fields: {maker: fk:Maker}\n")
    bad = runner.invoke(app, ["spec", "validate", "--spec", "bad.yaml", "--json"])
    assert bad.exit_code == 1
    payload = json.loads(bad.output)
    assert payload["valid"] is False and payload["file"] == "bad.yaml"
    assert payload["issues"][0]["code"] == "C230" and payload["issues"][0]["line"] == 7
    text = runner.invoke(app, ["spec", "validate", "--spec", "bad.yaml"])
    assert text.output.startswith("bad.yaml:7: C230: ")


def test_explain_knows_the_spec_codes() -> None:
    result = CliRunner().invoke(app, ["explain", "C230"])
    assert result.exit_code == 0 and "relation" in result.output.lower()


# the module table -----------------------------------------------------------------


def test_the_module_table_matches_the_modules() -> None:
    require_modules()
    import importlib

    for name, known in catalog.MODULES.items():
        conf = importlib.import_module(f"karni_{name}.conf")
        prefix = f"KARNI_{name.upper()}_"
        options = {key[len(prefix) :].lower() for key in conf.DEFAULTS if key.startswith(prefix)}
        assert set(known.options) == options, name
        source = (
            REPO_ROOT / "modules" / f"karni-{name}" / f"karni_{name}" / "models.py"
        ).read_text()
        classes = {
            node.name
            for node in ast.parse(source).body
            if isinstance(node, ast.ClassDef)
            and not node.name.startswith("Abstract")
            and any(getattr(base, "id", "") == "BaseModel" for base in node.bases)
        }
        assert classes <= set(known.models), name


# normalising and writing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "canonical"),
    [
        ("str:255", "str"),
        ("String:80?", "str:80?"),
        ("decimal:10:2", "decimal"),
        ("choice:a,b", "choice:a|b"),
        ("state:a,b,c", "state:a>b|b>c"),
        ("state:b>c|a>b", "state:b>c|a>b"),
        ("money:eur", "money:EUR"),
        ("percent:0:50?", "percent::50?"),
        ("percent:0:100", "percent"),
    ],
)
def test_canonical_fields(token: str, canonical: str) -> None:
    assert canonical_field("f", token) == canonical


def test_the_writer_round_trips_awkward_strings() -> None:
    data = {
        "a": "*",
        "b": ["role:staff", "owned:x", "-created_at", "yes", "1", "null", "a, b"],
        "c": {"*": "all", "x.y:view": "own"},
        "d": "state:a>b|b>c",
        "e": {"nested": {"list": [1, True, None]}},
    }
    assert yaml.safe_load(emit.dump(data)) == data


# export ---------------------------------------------------------------------------


def _facts() -> dict[str, Any]:
    return {
        "user_model": "karni_accounts.User",
        "apps": [],
        "viewsets": [],
        "settings": {"KARNI_ROLES": {"staff": {}}},
        "shipped_roles": {},
        "modules": [],
        "seeders": {},
    }


def _example_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite3'}")
    for name in ("DJANGO_SETTINGS_MODULE", "KARNI_PAYMENTS_PROVIDER", "KARNI_2FA"):
        monkeypatch.delenv(name, raising=False)


def test_export_eventhub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_modules("karni-payments")
    _example_env(monkeypatch, tmp_path)
    exported = export_project(REPO_ROOT / "examples" / "eventhub", docker=False)
    report = validate_text(exported.text())
    assert report.ok, [issue.render("eventhub") for issue in report.issues]
    data = exported.data
    events = data["apps"]["events"]["entities"]
    assert events["Venue"]["access"] == {
        "read": "public",
        "write": ["role:organizer", "role:staff"],
    }
    assert events["Booking"]["fields"]["status"] == (
        "state:pending>confirmed|pending>cancelled|confirmed>cancelled"
    )
    assert events["Booking"]["fields"]["payment"] == "fk:karni_payments.Payment?"
    assert events["Event"]["access"] == "code"  # Where(...) is not a spec shape
    assert data["modules"] == {
        "payments": {"checkout_validator": "events.payments.validate_checkout"}
    }
    assert {"home": "dashboard"} in data["pages"] and {"login": "login"} in data["pages"]
    assert any("SearchField" in line for line in exported.left_out)
    assert any("/events/$id/dashboard" in line for line in exported.left_out)


def test_export_social_leads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _example_env(monkeypatch, tmp_path)
    root = REPO_ROOT / "examples" / "social-leads"
    monkeypatch.chdir(root)
    out = tmp_path / "karni.yaml"
    result = CliRunner().invoke(app, ["spec", "export", "-o", str(out), "--no-docker"])
    assert result.exit_code == 0, result.output
    assert "not in the spec: crm.Lead.email" in result.output
    report = validate_text(out.read_text())
    assert report.ok, [issue.render("social-leads") for issue in report.issues]
    lead = report.spec.apps["crm"].entities["Lead"]  # type: ignore[union-attr]
    assert lead.owner == "workspace__members" and lead.audit is True
    assert report.spec.roles["member"].grants == {"crm.*": "own"}  # type: ignore[union-attr]
    again = CliRunner().invoke(app, ["spec", "export", "-o", str(out), "--no-docker"])
    assert again.exit_code == 1 and "C246" in str(again.exception)


# the round trip -------------------------------------------------------------------

ROUND_TRIP = """\
version: 1
app: {name: Round Trip, kind: app}
modules:
  payments: {provider: test}
features:
  two_factor: true
  email_code_login: true
  social_login: [google, apple]
  terms: {version: "2026-11", url: /terms/}
  user_grants: true
  api_cache: {ttl: 90}
roles:
  staff: {name: Staff, system: true, grants: {"*": all}}
  instructor: {grants: {classes.session: own, classes.studio:view: all}}
  member: {name: Member, default: true, grants: {classes.booking: own}}
apps:
  classes:
    entities:
      Studio:
        fields:
          name: str:120
          slug: slug:name
          address: text?
          site: url?
          phone: phone?
          country: country
          rating: decimal:3:1?
          photo: image?
          tags: array:str:30?
          meta: json:queried?
        key: slug
        search: name
        global_search: true
        access: {read: public, write: "role:staff"}
        cache: 600
      Session:
        fields:
          studio: fk:Studio
          instructor: fk:User
          title: str:200
          starts_at: datetime
          ends_at: datetime?
          day: date?
          capacity: int
          left: capacity:capacity
          price: money:EUR
          fee: money?
          discount: percent:0:50?
          ratio: float?
          is_open: bool
          ref: uuid
          level: choice:easy|hard
          during: datetimerange?
          nights: daterange?
          doc: file?
          spots: quantity
          contact: email:unique?
          code: slug:40?
        owner: instructor
        order: starts_at
        audit: true
        search: [title, level]
        global_search: {fields: [title], subtitle: studio__name, weight: 2}
        access: {read: "owned:instructor", write: "owned:instructor"}
      Booking:
        fields:
          session: fk:Session
          member: fk:User
          status: state:pending>paid|pending>cancelled|paid>refunded
          note: text?
          payment: fk:karni_payments.Payment?
          helpers: m2m:User?
          currency: currency?
        owner: member
        audit: [note, status]
        groups: {Booking: [session, member, status], Notes: [note]}
        scope_paths: {studio: session__studio}
        access: {read: authenticated, write: authenticated}
        cache: false
  shop:
    entities:
      Tag:
        fields: {label: "str:40"}
        access: {read: "role:staff", write: "role:staff"}
      Enquiry:
        fields: {email: email, body: text, profile: "o2o:User?", tags: "m2m:Tag?"}
        access: {read: "role:staff", write: "role:staff", create: public}
      Note:
        fields: {text: text}
        access: code
      Label:
        fields: {name: str}
pages:
  - home: dashboard
  - Session: [list, detail, form]
  - Booking: [list, detail]
  - about: blank
  - login: login
seed: {Studio: 3, Session: 40}
"""


def _preset(access: Any) -> str | None:
    """The ``--access`` preset of ``karni make viewset`` an access rule is (None: Granted)."""
    if access == "code":
        return None
    read, write, create = access.read, access.write, access.create
    if read == write == ["granted"] and create is None:
        return None
    if read == ["public"] and len(write) == 1 and write[0].startswith("role:"):
        return f"public-read:{write[0][5:]}"
    if read == write and len(read) == 1 and create == ["public"] and read[0].startswith("role:"):
        return f"public-create:{read[0][5:]}"
    if read == write and len(read) == 1 and create is None:
        return read[0]
    raise AssertionError(f"no karni make viewset preset for {access}")


def _insert(path: Path, model: str, inner: str, lines: list[str]) -> None:
    """Add ``lines`` to ``class <inner>`` inside ``class <model>`` (creating it)."""
    text = path.read_text()
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == model)
    rows = text.splitlines()
    nested = next((n for n in cls.body if isinstance(n, ast.ClassDef) and n.name == inner), None)
    body = [f"        {line}" for line in lines]
    if nested is not None:
        rows[nested.lineno : nested.lineno] = body
    else:
        rows[cls.lineno : cls.lineno] = [f"    class {inner}:", *body, ""]
    path.write_text("\n".join(rows) + "\n")


def _build_from_spec(root: Path, spec: schema.Spec) -> None:
    """What karni build (item A3) will do, here with the existing commands and plain edits."""

    def ok(*args: str) -> None:
        result = CliRunner().invoke(app, list(args))
        assert result.exit_code == 0, f"{args}: {result.output}\n{result.exception!r}"

    settings = root / "config" / "settings.py"
    for name in spec.modules:
        add_app(settings, f"karni_{name}")
    for label, application in spec.apps.items():
        ok("make", "app", label)
    for label, application in spec.apps.items():
        for name, entity in application.entities.items():
            args = ["make", "model", name, *(f"{f}:{t}" for f, t in entity.tokens().items())]
            args += ["--app", label, "--with", "viewset"]
            if entity.key:
                args += ["--key", entity.key]
            if entity.order:
                args += ["--order", entity.order[0]]
            preset = _preset(entity.access)
            if preset:
                args += ["--access", preset]
            if entity.search:
                args += ["--search", ",".join(entity.search)]
            ok(*args)
            models = root / label / "models.py"
            options = []
            if entity.owner:
                options.append(f"owner_field = {entity.owner!r}")
            if entity.audit:
                options.append(f"audit = {entity.audit!r}")
            if entity.scope_paths:
                options.append(f"scope_paths = {entity.scope_paths!r}")
            if entity.global_search:
                options.append(f"search = {_search_option(entity)!r}")
            if options:
                _insert(models, name, "Karni", options)
            if entity.groups:
                sets = [(title, {"fields": names}) for title, names in entity.groups.items()]
                _insert(models, name, "AdminMeta", [f"extra = {{'fieldsets': {sets!r}}}"])
            if entity.cache is not None:
                viewsets = root / label / "viewsets.py"
                line = (
                    'cache = Uncached(reason="spec")'
                    if entity.cache is False
                    else f"cache = Cache(ttl={entity.cache})"
                )
                text = viewsets.read_text().replace(
                    f"    model = {name}\n", f"    model = {name}\n    {line}\n"
                )
                viewsets.write_text("from karni.api import Cache, Uncached\n" + text)
            if entity.access == "code":
                viewsets = root / label / "viewsets.py"
                text = viewsets.read_text().replace(
                    f"model = {name}\n    access = Granted()",
                    f"model = {name}\n    access = Access(read=Where(lambda r: True), "
                    'write=HasRole("staff"))',
                )
                viewsets.write_text("from karni.api import Access, HasRole, Where\n" + text)
    for item in spec.pages:
        ((name, kinds),) = item.items()
        if name == "home":
            continue
        if name[:1].isupper():
            route = default_route(name)
            singular = route.removesuffix("s")
            for kind in kinds:
                page = route if kind == "list" else f"{singular}-{kind}"
                ok("make", "page", page, "--resource", route, "--kind", kind)
        elif kinds == ["login"]:
            ok("make", "page", name, "--kind", "login")
        else:
            ok("make", "page", name)
    for name, count in spec.seed.items():
        label = next(lb for lb, a in spec.apps.items() if name in a.entities)
        ok("make", "seeder", name, "--app", label, "--count", str(count))
    roles = {
        slug: {
            **({"name": role.name} if role.name else {}),
            "system": role.system,
            "grants": {
                (p if p == "*" or ":" in p else f"{p}:*"): s for p, s in role.grants.items()
            },
        }
        for slug, role in spec.roles.items()
    }
    features = spec.features
    extra = [
        f"KARNI_ROLES = {roles!r}",
        f"KARNI_ACCOUNTS_DEFAULT_ROLES = {[s for s, r in spec.roles.items() if r.default]!r}",
        f"KARNI_2FA = {features.two_factor!r}",
        f"KARNI_EMAIL_OTP = {features.email_code_login!r}",
        "KARNI_SOCIAL_TOKEN_PROVIDERS = "
        + repr({name: {"client_ids": ["test"]} for name in features.social_login}),
        f"KARNI_TERMS = {features.terms.model_dump(exclude_none=True)!r}" if features.terms else "",
        f"KARNI_USER_GRANTS = {features.user_grants!r}",
        "KARNI_API_CACHE = True" if features.api_cache else "",
        (
            f"KARNI_API_CACHE_TTL = {features.api_cache.ttl}"
            if isinstance(features.api_cache, schema.ApiCache)
            else ""
        ),
        *(
            f"{catalog.module_setting(module, option)} = {value!r}"
            for module, options in spec.modules.items()
            for option, value in options.items()
        ),
    ]
    settings.write_text(settings.read_text() + "\n" + "\n".join(extra) + "\n")


def test_round_trip_build_export_compare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    require_modules("karni-payments")
    original = validate_text(ROUND_TRIP)
    assert original.ok and original.spec is not None, original.issues
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    created = CliRunner().invoke(app, ["new", "Round Trip", "-o", str(tmp_path)])
    assert created.exit_code == 0, created.output
    root = tmp_path / "round_trip"
    monkeypatch.chdir(root)
    _build_from_spec(root, original.spec)
    _example_env(monkeypatch, tmp_path)
    exported = export_project(root, docker=False)
    assert exported.left_out == [
        "shop.Note: NoteViewSet's access is not one of the spec's shapes (access: code)"
    ]
    again = validate_text(exported.text())
    assert again.ok and again.spec is not None, [i.render("export") for i in again.issues]
    assert normalise(again.spec) == normalise(original.spec)


def test_api_cache_and_entity_cache() -> None:
    on = check(HEAD + "features: {api_cache: true}\n")
    ttl = check(HEAD + "features:\n  api_cache: {ttl: 300}\n")
    assert on.spec is not None and ttl.spec is not None, ttl.issues
    assert on.spec.features.api_cache is True
    assert normalise(on.spec)["features"]["api_cache"] == {"ttl": catalog.DEFAULT_CACHE_TTL}
    assert normalise(on.spec) == normalise(ttl.spec)  # true is the default lifetime
    off = check(HEAD + "features: {api_cache: false}\n")
    assert off.spec is not None and normalise(off.spec)["features"]["api_cache"] is False
    cached = check(SHOP + "        cache: 60\n      Note:\n        cache: false\n")
    assert cached.ok and cached.spec is not None, cached.issues
    entities = normalise(cached.spec)["apps"]["shop"]["entities"]
    assert entities["Product"]["cache"] == 60 and entities["Note"]["cache"] is False
    plain = check(SHOP + "        fields: {name: str}\n")
    assert plain.spec is not None
    assert normalise(plain.spec)["apps"]["shop"]["entities"]["Product"]["cache"] is None
    # an entity may say cache: without the feature (KARNI_API_CACHE may come from the environment)
    assert check(SHOP + "        {external: true, table: sales, cache: 30}\n").ok
    # without the feature, an external entity needs nothing: nothing is cached
    assert check(SHOP + "        {external: true, table: sales}\n").ok
    # the user and a module's model are tables Karni sees written
    assert check(
        HEAD + "features: {api_cache: true}\nmodules: {payments: {}}\napps:\n  shop:\n"
        "    entities:\n      Order: {fields: {buyer: fk:User, payment: fk:karni_payments.Payment}}\n"
    ).ok
    (issue,) = validate_text(
        HEAD + "features: {api_cache: true}\napps:\n  shop:\n    entities:\n"
        "      Sale: {external: true, table: sales, cache: false}\n"
        "      Line: {fields: {sale: fk:Sale}}\n"
    ).issues
    assert issue.code == "C521" and issue.path == "apps.shop.entities.Line"
    assert "Sale (through ?expand=)" in issue.message and "cache: 60" in issue.fix


def test_export_reads_the_cache_settings_and_declarations(tmp_path: Path) -> None:
    facts = _facts()
    facts["settings"] |= {"KARNI_API_CACHE": True, "KARNI_API_CACHE_TTL": 300}
    assert build(facts, tmp_path).data["features"] == {"api_cache": True}
    facts["settings"]["KARNI_API_CACHE_TTL"] = 45
    assert build(facts, tmp_path).data["features"] == {"api_cache": {"ttl": 45}}
    facts["settings"]["KARNI_API_CACHE"] = False
    assert "features" not in build(facts, tmp_path).data
    model = {
        "name": "Product",
        "label": "shop.Product",
        "base_model": True,
        "pk": "uuid",
        "managed": True,
        "db_table": "shop_product",
        "proxy": False,
        "fields": [],
        "ordering": [],
        "karni": {},
        "admin_meta": {},
        "api_meta": [],
    }
    facts["apps"] = [
        {
            "label": "shop",
            "name": "shop",
            "models": [
                model,
                {**model, "name": "Price", "label": "shop.Price", "db_table": "shop_price"},
                {**model, "name": "Stock", "label": "shop.Stock", "db_table": "shop_stock"},
                {**model, "name": "Note", "label": "shop.Note", "db_table": "shop_note"},
            ],
        }
    ]
    granted = {"read": {"granted": True}, "write": {"granted": True}}

    def viewset(name: str, cache: Any) -> dict[str, Any]:
        return {
            "class": f"shop.viewsets.{name}ViewSet",
            "route": name.lower() + "s",
            "model": f"shop.{name}",
            "access": granted,
            "search_fields": [],
            "cache": cache,
        }

    facts["viewsets"] = [
        viewset("Product", {"ttl": 60, "depends_on": []}),
        viewset("Price", {"ttl": None, "depends_on": ["shop.Stock"]}),
        viewset("Stock", {"uncached": "spec"}),
        viewset("Note", {"uncached": "levels change every second"}),
    ]
    exported = build(facts, tmp_path)
    entities = exported.data["apps"]["shop"]["entities"]
    assert entities["Product"]["cache"] == 60
    assert "cache" not in entities["Price"]  # Cache() without a ttl follows the setting
    assert entities["Stock"]["cache"] is False and entities["Note"]["cache"] is False
    assert exported.left_out == [
        "shop.Price: Cache depends_on shop.Stock",
        'shop.Note: the reason of Uncached, "levels change every second" (the spec writes "spec")',
    ]
    assert validate_text(exported.text()).ok


def test_was_pk_and_database_in_the_normal_form() -> None:
    plain = check(SHOP + "        fields: {code: str}\n")
    renamed = check(
        SHOP + "        was: Item\n        fields: {code: {type: 'str:255', was: sku}}\n"
    )
    assert plain.spec is not None and renamed.spec is not None, renamed.issues
    assert normalise(renamed.spec) == normalise(plain.spec)  # was says how, not what
    assert renamed.spec.apps["shop"].entities["Product"].renamed() == {"code": "sku"}
    product = normalise(plain.spec, pk="bigint")["apps"]["shop"]["entities"]["Product"]
    assert product["pk"] == "bigint" and product["database"] is None
    external = check(SHOP + "        {external: true, table: sales, database: default}\n")
    assert external.spec is not None, external.issues
    sale = normalise(external.spec)["apps"]["shop"]["entities"]["Product"]
    assert sale["pk"] is None and sale["database"] is None and sale["table"] == "sales"
    assert check(SHOP + "        {database: warehouse}\n").ok  # validate alone cannot tell
    found = validate_text(SHOP + "        database: warehouse\n", databases=["default"]).issues
    assert [issue.code for issue in found] == ["C252"]
