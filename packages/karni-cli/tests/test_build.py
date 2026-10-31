"""``karni build`` (experimental): the spec applied to a real project, idempotently.

One project is built once per module from an empty ``karni new`` render and
the A1 fixture (``harbour-yoga.yaml``), with every step real: migrations,
migrate, seed, the project's own tests and ``karni check``'s backend. The
frontend tools are stubbed (the suite runs no npm): ``openapi-typescript``
writes a stub, and ESLint and jscpd pass. The other tests build a copy of
that project, with the types, test and check steps skipped to keep the suite
fast, or a project of their own.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli.builder import output, record, render, run
from karni_cli.commands import check as check_mod
from karni_cli.commands import types as types_mod
from karni_cli.main import app

from .conftest import REPO_ROOT, TEMPLATE, require_modules
from .test_spec import FIXTURE

BUILD_SCHEMA = REPO_ROOT / "docs" / "assets" / "karni-build.schema.json"
SNAPSHOT = Path(__file__).parent / "fixtures" / "spec" / "harbour-yoga.build.json"
_FAST = ("types", "test", "check")


def _render(parent: Path, name: str, kind: str = "app") -> Path:
    from cookiecutter.main import cookiecutter

    from karni_cli.commands.new import write_agent_adapters

    cookiecutter(
        str(TEMPLATE),
        no_input=True,
        extra_context={"project_name": name, "kind": kind},
        output_dir=str(parent),
    )
    root = parent / name.lower().replace(" ", "_")
    write_agent_adapters(root)
    return root


def _env(mp: pytest.MonkeyPatch, root: Path) -> None:
    mp.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    mp.setenv("DATABASE_URL", f"sqlite:///{root / 'db.sqlite3'}")
    mp.setenv("KARNI_SOCIAL_GOOGLE_CLIENT_IDS", "google-client")
    mp.setenv("KARNI_SOCIAL_APPLE_CLIENT_IDS", "apple-client")
    mp.setenv("PYTHONDONTWRITEBYTECODE", "1")
    mp.setenv("KARNI_CACHE", "locmem")  # karni new's .env points at the compose Redis
    for name in ("DJANGO_SETTINGS_MODULE", "KARNI_PAYMENTS_PROVIDER", "KARNI_2FA", "CI"):
        mp.delenv(name, raising=False)
    mp.chdir(root)


def _frontend(mp: pytest.MonkeyPatch) -> None:
    """No npm in the suite: openapi-typescript writes a stub, ESLint and jscpd pass."""

    def stub(project: Path, schema: Path, out: Path) -> list[str]:
        code = "import sys; open(sys.argv[1], 'w').write('export type paths = {};\\n')"
        return [sys.executable, "-c", code, str(out)]

    mp.setattr(types_mod, "_openapi_typescript_cmd", stub)
    mp.setattr(check_mod, "_frontend_lint", lambda project, capture=None: 0)
    mp.setattr(check_mod, "_frontend_duplication", lambda project, capture=None: 0)


def _fast(mp: pytest.MonkeyPatch) -> None:
    """Skip the types, test and check steps (the module's first build runs them)."""
    for name in _FAST:
        mp.setitem(run.STEP_RUNNERS, name, lambda root, state, opts: "skipped: not in this test")


def _build(*args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["build", *args])
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.output


def _files(root: Path) -> dict[str, str]:
    """Every file of the project but the databases and caches, by its sha256."""
    found = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and "__pycache__" not in rel and not rel.endswith(".sqlite3"):
            found[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def _rows(root: Path, sql: str) -> list[Any]:
    with sqlite3.connect(root / "db.sqlite3") as db:
        return db.execute(sql).fetchall()


def _edit(path: Path, *pairs: tuple[str, str]) -> None:
    text = path.read_text()
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path.write_text(text)


@dataclass
class Built:
    root: Path
    output: str


@pytest.fixture(scope="module")
def harbour(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Built]:
    """The fixture spec built into an empty ``karni new`` project, every step real.

    npm is stubbed as the suite's conftest stubs it, and so are the frontend tools.
    """
    from karni_cli import scaffold

    require_modules("karni-payments", "karni-site")
    parent = tmp_path_factory.mktemp("build-harbour")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KARNI_TEMPLATES", str(TEMPLATE))
        mp.setattr(
            scaffold,
            "run_npm",
            lambda argv, cwd: subprocess.CompletedProcess(argv, 127, "", "npm disabled"),
        )
        created = CliRunner().invoke(
            app, ["new", "Harbour Yoga", "--kind", "site+app", "-o", str(parent)]
        )
        assert created.exit_code == 0, created.output
        root = parent / "harbour_yoga"
        shutil.copy(FIXTURE, root / "karni.yaml")
        _env(mp, root)
        _frontend(mp)
        code, out = _build()
        assert code == 0, out
        yield Built(root, out)


@pytest.fixture(autouse=True)
def _project_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))


@pytest.fixture
def copy(harbour: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the built project (its database too), with the slow steps skipped."""
    root = tmp_path / "harbour_yoga"
    shutil.copytree(harbour.root, root, ignore=shutil.ignore_patterns("__pycache__"))
    _env(monkeypatch, root)
    _frontend(monkeypatch)
    _fast(monkeypatch)
    return root


# from an empty project ------------------------------------------------------------


def test_a_spec_builds_an_empty_project_that_passes_its_tests_and_check(harbour: Built) -> None:
    root, out = harbour.root, harbour.output
    lines = out.splitlines()
    assert "25 changes, 0 risky." in lines
    steps = {line.split()[0]: line for line in lines if line[:1].isalpha() and "  " in line}
    assert steps["modules"].endswith("karni add payments")
    assert "classes/migrations/0001_initial.py" in steps["migrations"]
    assert "Studio 3, Session 40, Booking 200" in steps["seed"]
    assert " passed in " in steps["test"] and "failed" not in steps["test"]  # the site app's too
    assert steps["check"].split() == ["check", "ok"]
    assert lines[-1] == "Built: the project matches karni.yaml."
    # Karni's code and the project's live in separate files
    karni = (root / "classes" / "karni" / "models.py").read_text()
    assert karni.startswith('"""Written by karni build from karni.yaml. Do not edit it')
    assert "class Session(BaseModel):" in karni and "abstract = True" in karni
    ours = (root / "classes" / "models.py").read_text()
    assert "from classes.karni import models as karni\n" in ours
    assert "class Session(karni.Session):\n" in ours
    assert (
        "class SessionViewSet(karni.SessionViewSet):" in (root / "classes/viewsets.py").read_text()
    )
    assert "count = 40" in (root / "classes/karni/seeds.py").read_text()
    settings = (root / "config" / "settings.py").read_text()
    block = settings[
        settings.index("# karni:spec start") : settings.index("karni_settings(globals())")
    ]
    assert 'KARNI_ACCOUNTS_DEFAULT_ROLES = ["member"]' in block and "KARNI_2FA = True" in block
    assert '"classes.session:*": "own"' in block  # own:instructor is Karni.owner_field
    routes = (root / "frontend" / "src" / "routes.tsx").read_text()
    assert 'import SessionsPage from "./pages/karni/sessions";' in routes
    page = (root / "frontend/src/pages/karni/session-detail.tsx").read_text()
    assert page.startswith("// Written by karni build") and page.count("\n") <= 50
    test = (root / "classes/tests/karni/test_booking.py").read_text()
    assert 'self.assert_crud(BookingViewSet, "staff")' in test
    assert "self.assert_isolated(BookingViewSet)\n" in test  # staff reads every row
    # the record fingerprints every Karni-owned file and block
    rec = record.load(root)
    assert rec.entities == ["classes.Booking", "classes.Session", "classes.Studio"]
    assert set(rec.blocks) == {"config/settings.py", *record.layout.ROUTES_BLOCKS}
    assert rec.files["classes/karni/models.py"] == record.digest(karni)
    # demo rows only in the tables it created: the module's are empty
    assert _rows(root, "select count(*) from karni_payments_payment") == [(0,)]
    assert record.pending(root) == {}


def test_the_ai_module_is_added_wired_and_checked(
    copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``modules: ai`` adds karni-ai with its provider; karni check passes with the test one."""
    require_modules("karni-ai")
    monkeypatch.setitem(run.STEP_RUNNERS, "check", run._check)  # the fixture skips it
    for name in ("KARNI_AI_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(name, raising=False)
    _edit(copy / "karni.yaml", ("modules:\n", "modules:\n  ai: {provider: test}\n"))
    plan = CliRunner().invoke(app, ["plan", "--offline"]).output
    assert "  + ai: provider test" in plan
    code, out = _build()
    assert code == 0, out
    steps = {
        line.split()[0]: line for line in out.splitlines() if line[:1].isalpha() and "  " in line
    }
    assert steps["modules"].endswith("karni add ai")
    settings = (copy / "config" / "settings.py").read_text()
    apps_block = settings[: settings.index("# karni:apps")]
    assert '"karni_ai",' in apps_block[apps_block.rindex("INSTALLED_APPS") :]
    block = settings[settings.index("# karni:spec start") : settings.index("# karni:spec end")]
    assert 'KARNI_AI_PROVIDER = "test"' in block
    assert "ANTHROPIC" not in block and "MODEL" not in block
    assert '"karni-ai' in (copy / "pyproject.toml").read_text()
    assert (copy / ".karni" / "modules" / "ai.md").is_file()
    assert _rows(copy, "select count(*) from karni_ai_aicall") == [(0,)]
    # karni check runs the module's checks: the test provider needs no key and no model.
    assert steps["check"].split() == ["check", "ok"], out


def test_a_second_build_writes_nothing(copy: Path) -> None:
    before = _files(copy)
    code, out = _build()
    assert (code, out) == (0, "Nothing to build: the project matches karni.yaml.\n")
    assert _files(copy) == before
    plan = CliRunner().invoke(app, ["plan", "--offline"])
    assert plan.output == "No changes: the project matches karni.yaml.\n"


# changes --------------------------------------------------------------------------


def test_an_entity_added_and_fields_changed_and_renamed_keep_the_data(copy: Path) -> None:
    spec = copy / "karni.yaml"
    _edit(
        spec,
        (
            '        fields: {name: "str:120", slug: "slug:name", address: "text?"}\n',
            (
                '        fields: {label: {type: "str:150", was: name}, slug: "slug:label", '
                'address: "text?", phone: "phone?"}\n'
            ),
        ),
        ("        search: [name]\n", "        search: [label]\n"),
        (
            "pages:\n",
            (
                "      Review:\n        fields: {session: fk:Session, stars: int}\n"
                '        access: {read: public, write: "role:staff"}\n'
                "      Room:\n        fields: {code: str}\npages:\n"
            ),
        ),
        ("Booking: 200}", "Booking: 200, Review: 5, Room: 0}"),
    )
    names = _rows(copy, "select name from classes_studio order by name")
    code, out = _build()
    assert code == 0, out
    assert "  ~ classes.Studio.label: from name, str:120 -> str:150" in out
    assert "classes/migrations/0002_karni_renames.py" in out
    assert _rows(copy, "select label from classes_studio order by label") == names
    assert _rows(copy, "select count(*) from classes_review") == [(5,)]
    assert _rows(copy, "select count(*) from classes_room") == [(0,)]  # seed 0 skips it
    assert "class Review(karni.Review):" in (copy / "classes" / "models.py").read_text()
    assert (copy / "classes/tests/karni/test_review.py").is_file()
    # a required field on a table with rows needs values: on an empty one it needs none
    _edit(spec, ("        fields: {code: str}\n", "        fields: {code: str, floor: int}\n"))
    code, out = _build()
    assert code == 0, out
    _edit(spec, ("session: fk:Session, stars: int}", "session: fk:Session, stars: int, n: int}"))
    code, out = _build()
    assert code == 1 and "error C277: makemigrations failed." in out, out
    assert "impossible to add a non-nullable field" in out
    _edit(spec, ("stars: int, n: int}", 'stars: int, n: "int?"}'))
    code, out = _build()
    assert code == 0 and "continues" not in out, out
    assert not list((copy / "classes" / "migrations").glob("*karni_renames*"))[1:]
    # an entity renamed: its table, its rows and the project's classes follow
    _edit(
        spec,
        ("      Review:\n", "      Rating:\n        was: Review\n"),
        ("Review: 5", "Rating: 5"),
    )
    code, out = _build()
    assert code == 0 and "  ~ classes.Rating: from Review, rows kept" in out, out
    assert _rows(copy, "select count(*) from classes_rating") == [(5,)]
    assert "class Rating(karni.Rating):" in (copy / "classes" / "models.py").read_text()
    assert "class RatingViewSet(karni.RatingViewSet):" in (copy / "classes/viewsets.py").read_text()
    assert (copy / "classes/tests/karni/test_rating.py").is_file()
    assert not (copy / "classes/tests/karni/test_review.py").exists()


def test_the_destructive_guard_and_a_removal(copy: Path) -> None:
    spec = copy / "karni.yaml"
    _edit(spec, ("pages:\n", "      Review:\n        fields: {stars: int}\npages:\n"))
    assert _build()[0] == 0
    before = _files(copy)
    _edit(
        spec,
        ("      Review:\n        fields: {stars: int}\n", ""),
        ('          note: "text?"\n', ""),
        (", Notes: [note]}", "}"),
    )
    code, out = _build()
    assert code == 1
    assert "! - classes.Review, its table and rows are dropped (10 rows)" in out, out
    assert "error C270: 2 risky changes" in out and "--allow-destructive" in out
    assert {k: v for k, v in _files(copy).items() if k != "karni.yaml"} == {
        k: v for k, v in before.items() if k != "karni.yaml"
    }
    code, out = _build("--allow-destructive")
    assert code == 0, out
    for rel in ("classes/models.py", "classes/viewsets.py"):
        assert "Review" not in (copy / rel).read_text()
    assert not (copy / "classes/tests/karni/test_review.py").exists()
    assert "note" not in (copy / "classes/karni/models.py").read_text()


def test_a_key_type_switch_and_a_module_removal_are_refused(copy: Path) -> None:
    spec = copy / "karni.yaml"
    _edit(spec, ("        key: slug\n", "        key: slug\n        pk: bigint\n"))
    code, out = _build("--allow-destructive")
    assert code == 1 and "error C272: karni.yaml switches the key type of classes.Studio" in out
    _edit(spec, ("        pk: bigint\n", ""), ("modules:\n  payments:\n    provider: stripe\n", ""))
    code, out = _build("--allow-destructive")
    assert code == 1 and "error C271:" in out and "payments" in out


# ownership ------------------------------------------------------------------------


def test_a_hand_edit_stops_the_build_then_force_or_adopt(copy: Path) -> None:
    api = copy / "classes" / "karni" / "api.py"
    _edit(api, ('    search_fields = ("name",)\n', '    search_fields = ("name", "address")\n'))
    before = _files(copy)
    code, out = _build()
    assert code == 1
    assert "classes/karni/api.py: edited by hand (line 14)" in out, out
    assert '    -    search_fields = ("name",)' in out
    assert (
        "error C273: classes/karni/api.py was edited by hand, so karni build wrote nothing." in out
    )
    assert (
        "1. move the change into classes/viewsets.py" in out
        and "--adopt classes/karni/api.py" in out
    )
    assert _files(copy) == before
    edited = api.read_text()
    code, out = _build("--force")
    assert code == 0, out
    assert (copy / "classes/karni/api.py.orig").read_text() == edited
    assert '("name", "address")' not in api.read_text()
    _edit(api, ('    search_fields = ("name",)\n', '    search_fields = ("name", "address")\n'))
    code, out = _build("--adopt", "classes/karni/api.py")
    assert code == 0, out
    assert "adopted (the project's now, karni build leaves it): classes/karni/api.py" in out
    assert record.load(copy).adopted == ["classes/karni/api.py"]
    assert '("name", "address")' in api.read_text()
    plan = CliRunner().invoke(app, ["plan", "--offline"]).output
    assert "  ~ classes.Studio search: name, address -> name (not managed)" in plan
    code, out = _build("--adopt", "classes/models.py")
    assert code == 1 and "error C274: --adopt classes/models.py: karni build does not own it" in out


def test_the_projects_own_files_are_never_rewritten(copy: Path) -> None:
    models = copy / "classes" / "models.py"
    _edit(
        models,
        (
            "class Studio(karni.Studio):\n" + render.STUB_LINE + "\n",
            "class Studio(karni.Studio):\n    def city(self) -> str:\n        return 'Bristol'\n",
        ),
    )
    ours = {rel: (copy / rel).read_bytes() for rel in ("classes/models.py", "classes/viewsets.py")}
    _edit(
        copy / "karni.yaml",
        ("          capacity: int\n", '          capacity: int\n          level: "int?"\n'),
    )
    code, out = _build()
    assert code == 0, out
    assert all((copy / rel).read_bytes() == text for rel, text in ours.items())
    assert (
        "level = models.IntegerField(null=True, blank=True)"
        in (copy / "classes/karni/models.py").read_text()
    )


# escape hatches, projects built by hand, keys and databases -----------------------


def _project(tmp_path: Path, mp: pytest.MonkeyPatch, name: str, spec: str) -> Path:
    mp.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    root = _render(tmp_path, name)
    (root / "karni.yaml").write_text(textwrap.dedent(spec))
    _env(mp, root)
    _frontend(mp)
    _fast(mp)
    return root


STORE = """\
    version: 1
    app: {name: Store Ops}
    apps:
      stock:
        entities:
          Part:
            fields: {sku: "str:20", name: str}
            pk: bigint
            access: code
          Sale:
            fields: {sku: "str:20", amount: int}
            external: true
            table: sales
            database: warehouse
          Mapping:
            fields: {sku: "str:20", label: "str:80"}
            database: warehouse
    pages:
      - home: dashboard
      - Part: [list]
      - reports: code
    seed: {Part: 4}
    """


def test_bigint_keys_an_external_table_a_second_database_and_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, monkeypatch, "Store Ops", STORE)
    settings = root / "config" / "settings.py"
    settings.write_text(
        settings.read_text()
        + '\nDATABASES["warehouse"] = env.db_url("WAREHOUSE_DATABASE_URL")  # noqa: F821\n'
    )
    monkeypatch.setenv("WAREHOUSE_DATABASE_URL", f"sqlite:///{root / 'warehouse.sqlite3'}")
    with sqlite3.connect(root / "warehouse.sqlite3") as db:
        db.execute("create table sales (id integer primary key, sku varchar(20), amount int)")
    code, out = _build()
    assert code == 0, out
    karni = (root / "stock" / "karni" / "models.py").read_text()
    assert "class Part(BigIntBaseModel):" in karni
    assert "class Sale(models.Model):" in karni and 'db_table = "sales"' in karni
    assert "class Mapping(UUIDModel, TimestampedModel):" in karni
    api = (root / "stock" / "karni" / "api.py").read_text()
    assert "# access: code in karni.yaml: stock/viewsets.py declares it." in api
    assert "    access = Granted()\n" in (root / "stock" / "viewsets.py").read_text()
    assert not (root / "stock/tests/karni/test_mapping.py").exists()  # not on default
    assert not (root / "stock/tests/karni/test_sale.py").exists()  # another system's table
    assert _rows(root, "select count(*) from stock_part") == [(4,)]
    with sqlite3.connect(root / "warehouse.sqlite3") as db:
        assert db.execute("select count(*) from stock_mapping").fetchall() == [(10,)]
    assert "pages/karni/reports.tsx" not in out and "+ reports: code (not managed)" in out
    # the project's own page at /reports: access: code and the page match the spec as they are
    (root / "frontend/src/pages/reports.tsx").write_text(
        'import { Page, Stat } from "@karni/ui";\n\nexport default function ReportsPage() {\n'
        '    return <Page title="Reports"><Stat label="Parts" value={4} /></Page>;\n}\n'
    )
    route = (
        '    createRoute({ getParentRoute: () => root, path: "/reports", component: ReportsPage }),'
    )
    _edit(
        root / "frontend/src/routes.tsx",
        (
            "// karni:page-imports",
            'import ReportsPage from "./pages/reports";\n// karni:page-imports',
        ),
        ("    // karni:routes", f"{route}\n    // karni:routes"),
    )
    _edit(
        root / "stock" / "viewsets.py",
        (
            "    access = Granted()\n",
            '    access = Access(read=Granted(), write=HasRole("staff"))\n',
        ),
        ("from karni.api import Granted\n", "from karni.api import Access, Granted, HasRole\n"),
    )
    code, out = _build()  # Karni's test of Part follows the project's own access
    assert code == 0 and "files       1 written: 1 Karni's" in out, out
    assert (
        'assert_crud(PartViewSet, "staff")' in (root / "stock/tests/karni/test_part.py").read_text()
    )
    assert _build() == (0, "Nothing to build: the project matches karni.yaml.\n")
    # a page karni.yaml wants where the project has its own is refused
    _edit(root / "karni.yaml", ("  - reports: code\n", "  - reports: blank\n"))
    code, out = _build()
    assert code == 1 and "error C275: frontend/src/routes.tsx already routes /reports" in out


def test_a_project_built_by_hand_gets_only_what_is_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, monkeypatch, "Hand Shop", "version: 1\napp: {name: Hand Shop}\n")
    runner = CliRunner()
    for args in (
        ["make", "app", "shop"],
        ["make", "model", "Product", "name:str:120", "--app", "shop", "--with", "viewset"],
        ["make", "migration"],
    ):
        assert runner.invoke(app, args).exit_code == 0, args
    exported = runner.invoke(app, ["spec", "export", "-o", "karni.yaml", "--force"])
    assert exported.exit_code == 0, exported.output
    models = root / "shop" / "models.py"
    hand = models.read_text()
    assert 'Product: {fields: {name: "str:120"}}' in (root / "karni.yaml").read_text()
    (root / "karni.yaml").write_text(
        textwrap.dedent(
            """\
            version: 1
            app: {name: Hand Shop}
            apps:
              shop:
                entities:
                  Product: {fields: {name: "str:120", color: "str:30?"}}
                  Invoice: {fields: {product: "fk:Product", total: "money:EUR"}}
            pages:
              - home: dashboard
            """
        )
    )
    plan = runner.invoke(app, ["plan", "--offline"]).output
    assert "  + shop.Product.color: str:30? (not managed)" in plan
    assert "  + shop.Invoice: (product fk:Product, total money:EUR)" in plan
    code, out = _build()
    assert code == 0, out
    assert "Built. karni plan's 1 other change is in the project's own code" in out
    text = models.read_text()
    product = hand[hand.index("class Product(BaseModel):") :]
    assert product in text and "color" not in text  # the hand-written model is untouched
    assert text.endswith("class Invoice(karni.Invoice):\n" + render.STUB_LINE + "\n")
    assert record.load(root).entities == ["shop.Invoice"]


# the output -----------------------------------------------------------------------


def test_dry_run_writes_nothing_and_the_json_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_modules("karni-payments", "karni-site")
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    root = _render(tmp_path, "Harbour Yoga", "site+app")
    shutil.copy(FIXTURE, root / "karni.yaml")
    _env(monkeypatch, root)
    before = _files(root)
    code, out = _build("--dry-run")
    assert code == 0 and out.endswith("(dry run: nothing written)\n")
    assert "would create classes/karni/models.py (karni)" in out
    assert "would create classes/models.py (project)" in out
    result = CliRunner().invoke(app, ["build", "--dry-run", "--json"])
    assert _files(root) == before
    data = json.loads(result.output)
    assert output.checked(data) == data and data["status"] == "dry run"
    rendered = json.dumps(data, indent=2) + "\n"
    if os.environ.get("KARNI_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(rendered)
    assert SNAPSHOT.read_text() == rendered, (
        "The fixture's build changed. Check the difference, then rewrite the snapshot: "
        "KARNI_UPDATE_SNAPSHOTS=1 pytest tests/test_build.py"
    )


def test_the_published_build_schema_is_current() -> None:
    expected = json.dumps(output.json_schema(), indent=2) + "\n"
    assert BUILD_SCHEMA.read_text() == expected, (
        "docs/assets/karni-build.schema.json is stale. Regenerate it: "
        "python -m karni_cli.builder.output > docs/assets/karni-build.schema.json"
    )


def test_an_invalid_spec_builds_nothing(copy: Path) -> None:
    (copy / "karni.yaml").write_text("version: 1\napp: {name: X}\nfeatures: {two_factor: 3}\n")
    code, out = _build("--json")
    data = json.loads(out)
    assert code == 1 and data["status"] == "invalid" and data["issues"][0]["code"] == "C213"


def test_hand_edit_lines_and_the_record() -> None:
    edit = record.hand_edit(
        "a.py", "one\nTWO\nthree\nfour\nFIVE\n", "one\ntwo\nthree\nfour\nfive\n"
    )
    assert edit.lines == (2, 5) and edit.shown_lines() == "lines 2, 5"
    assert edit.diff == ("-two", "+TWO", "-five", "+FIVE")
    assert record.hand_edit("a.py", "x\ny\nz\n", "x\n").shown_lines() == "lines 2-3"
    rec = record.Record(spec="s", entities=["b.B", "a.A"], files={"z": "1", "a": "2"})
    assert json.loads(rec.text())["entities"] == ["a.A", "b.B"]
    assert list(json.loads(rec.text())["files"]) == ["a", "z"]


def test_seeding_skips_a_table_that_holds_rows(copy: Path) -> None:
    state = {"seed": ["classes.Studio"], "user": "karni_accounts.User"}
    assert (
        run._seed(copy, state, run.Options()) == "skipped: the tables it created hold rows already"
    )
