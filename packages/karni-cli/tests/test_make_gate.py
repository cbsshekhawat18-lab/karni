"""The ``karni make`` quality gate.

1. Scaffold a project (``karni new``), run EVERY generator — both the
   ``karni make <type>`` and ``karni make:<type>`` forms, chains included —
   and require every file they create or modify to pass ``karni rules
   --check``, ``ruff check`` (the project's defaults and a strict selection)
   and ``ruff format --check``; generated pages and components must parse
   and pages stay at 50 lines or fewer. The TSX parse uses the TypeScript
   compiler when node + typescript are available (``KARNI_TEST_NODE_MODULES``
   or packages/karni-ui/node_modules), else a structural check. With
   ``KARNI_TEST_NODE_MODULES`` pointing at an installed scaffold
   ``frontend/node_modules`` (with @karni/ui), ``tsc --noEmit`` and the
   project's ESLint config (karni/* rules included) run too.
2. Run the generated backend for real through the project interpreter
   (``karni make migration``, ``karni migrate``, ``manage.py check``), hit
   the generated endpoints with the Django test client, seed it
   (``manage.py karni_seed``), run the API tests ``karni make test`` wrote
   (they must pass), and run a generated module's standalone test suite.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import agent_data
from karni_cli.main import app

from .conftest import REPO_ROOT, TEMPLATE, require_modules
from .test_make import GENERATORS, ok, snapshot

DESIGNS = Path(__file__).parent / "fixtures" / "designs"

#: Every generator, both spellings, the chains, every --access / --on shape.
SEQUENCE: list[list[str]] = [
    ["make", "app", "events"],
    ["make:app", "shop"],
    ["make", "model", "Tag", "label:slug", "--app", "shop", "--with", "viewset",
     "--access", "public-read"],
    ["make", "model", "Venue", "name:str:120", "city:str?", "--app", "events"],
    ["make", "model", "Product", "name:str:120", "slug:slug:name", "price:money:EUR",
     "cost:money?", "rate:percent:0:100", "stock:quantity", "phone:phone?", "country:country?",
     "currency:currency?", "email:email:unique", "meta:json:queried", "tags:array:str:30?",
     "--app", "shop"],
    ["make:model", "Event", "title:str:200", "body:text?", "starts_at:datetime",
     "day:date?", "status:choice:draft|published|in-review", "organizer:fk:User",
     "venue:fk:Venue?", "capacity:int?", "ratio:float?", "price:decimal:8:2?",
     "is_open:bool", "contact:email?", "site:url?", "code:slug:40?", "meta:json",
     "ref:uuid", "doc:file?", "photo:image?", "tags:m2m:shop.Tag?", "profile:o2o:User?",
     "--app", "events", "-a", "--access", "owned:organizer", "--search", "title,status"],
    ["make", "model", "Booking", "venue:fk:Venue", "during:datetimerange", "nights:daterange?",
     "status:state:held>confirmed|held>cancelled|confirmed>cancelled", "seats:int",
     "left:capacity:seats", "--app", "events", "--with", "viewset"],
    ["make", "viewset", "Venue", "--app", "events", "--access", "staff"],
    ["make:test", "Venue", "--app", "events"],
    ["make", "factory", "Venue", "--app", "events"],
    ["make:factory", "Tag", "--app", "shop"],
    ["make", "seeder", "Venue", "--app", "events", "--count", "3"],
    ["make:seeder", "Event", "--app", "events"],
    ["make:serializer", "Venue", "--app", "events", "--reason", "adds a computed label"],
    ["make", "task", "send_digest", "--app", "events", "--retry", "3"],
    ["make:task", "plain_task", "--app", "events"],
    ["make", "schedule", "nightly-report", "--cron", "0 3 * * *", "--app", "events"],
    ["make:schedule", "digest", "--every", "15m", "--task", "events.tasks.send_digest",
     "--app", "events"],
    ["make", "event", "order_shipped", "--app", "events"],
    ["make", "listener", "stamp_event", "--on", "Event.created", "--app", "events"],
    ["make:listener", "sync_event", "--on", "Event.updated", "--queued", "--app", "events"],
    ["make", "listener", "purge_event", "--on", "events.Event.deleted", "--app", "events"],
    ["make", "listener", "email_tracking", "--on", "order_shipped", "--app", "events"],
    ["make", "listener", "queue_tracking", "--on", "events.events.order_shipped",
     "--queued", "--app", "events"],
    ["make", "command", "send_reminders", "--app", "events"],
    ["make:command", "rebuild_index", "--app", "shop"],
    ["make", "service", "stripe_client", "--app", "events"],
    ["make", "middleware", "RequestTiming", "--app", "events"],
    ["make:middleware", "Audit", "--app", "shop"],
    ["make", "page", "reports"],
    ["make:page", "tag-list", "--resource", "tags", "--kind", "list"],
    ["make", "page", "tag-detail", "--resource", "tags", "--kind", "detail"],
    ["make", "page", "tag-form", "--resource", "tags", "--kind", "form", "--title", "Tag"],
    ["make", "component", "StatusBadge"],
    ["make:component", "PriceTag", "--role", "price-tag"],
    ["make", "site", "website"],
    ["make:view", "about", "--app", "website"],
    ["make", "view", "service", "--app", "website", "--path", "/services/<slug:slug>/"],
    ["make", "module", "live-chat"],
]  # fmt: skip

TS_PARSE = """
// node -e: process.argv is [node, ...args] (no script path).
const ts = require(process.argv[1]);
const fs = require("fs");
let bad = 0;
for (const file of process.argv.slice(2)) {
  const source = ts.createSourceFile(
    file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  for (const d of source.parseDiagnostics) {
    bad += 1;
    console.log(file + ": " + ts.flattenDiagnosticMessageText(d.messageText, "\\n"));
  }
}
process.exit(bad ? 1 : 0);
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Gate Check", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "gate_check"
    monkeypatch.chdir(root)
    return root


def _generate(project: Path) -> list[str]:
    before = snapshot(project)
    for args in SEQUENCE:
        ok(*args)
    after = snapshot(project)
    return sorted(rel for rel, text in after.items() if before.get(rel) != text)


def _ruff_available() -> bool:
    return importlib.util.find_spec("ruff") is not None


def _ruff(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _typescript() -> tuple[str, Path] | None:
    node = shutil.which("node")
    if node is None:
        return None
    candidates = [
        os.environ.get("KARNI_TEST_NODE_MODULES"),
        REPO_ROOT / "packages/karni-ui/node_modules",
    ]
    for base in candidates:
        if base and (Path(base) / "typescript" / "lib" / "typescript.js").is_file():
            return node, Path(base) / "typescript" / "lib" / "typescript.js"
    return None


@pytest.mark.parametrize(
    "layout",
    [
        "templates/project/{{cookiecutter.project_slug}}/frontend/src/layout.tsx",
        "examples/eventhub/frontend/src/layout.tsx",
        "examples/social-leads/frontend/src/layout.tsx",
    ],
)
def test_the_menu_comes_from_karni_ui(layout: str) -> None:
    """The nav rules live once, in @karni/ui's routeNavItems (its vitest suite pins them)."""
    source = (REPO_ROOT / layout).read_text(encoding="utf-8")
    assert "routeNavItems(Object.keys(router.routesByPath), {" in source
    assert 'signedIn: status === "authenticated"' in source
    assert "function inNav" not in source and "function label" not in source


def test_the_scaffold_guards_every_page_but_the_sign_in_page() -> None:
    source = (
        REPO_ROOT / "templates/project/{{cookiecutter.project_slug}}/frontend/src/layout.tsx"
    ).read_text(encoding="utf-8")
    assert "<AuthGuard explain>" in source and "isSignInRoute(pathname)" in source
    home = (
        REPO_ROOT / "templates/project/{{cookiecutter.project_slug}}/frontend/src/pages/home.tsx"
    ).read_text(encoding="utf-8")
    assert "<Dashboard" in home and "fetchHealth" not in home


def _balanced(text: str) -> bool:
    """Structural fallback: brackets balance outside string literals."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    quote = ""
    for ch in text:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in pairs and (not stack or stack.pop() != pairs[ch]):
            return False
    return not stack and not quote


def test_every_generator_runs_and_its_output_is_clean(project: Path) -> None:
    used = {args[0].split(":", 1)[1] if ":" in args[0] else args[1] for args in SEQUENCE}
    # `migration` needs a project interpreter: covered by test_make.py (argv) and
    # test_generated_backend_runs_for_real below.
    assert used == GENERATORS - {"migration"}
    changed = _generate(project)
    assert "config/settings.py" in changed and "frontend/src/routes.tsx" in changed
    assert "config/urls.py" in changed and "website/templates/website/service.html" in changed

    # 1. karni rules --check: every enforced rule, on every generated file.
    checked = [project / rel for rel in changed if Path(rel).suffix in {".py", ".ts", ".tsx"}]
    findings = agent_data.check(checked, project)
    assert findings == [], findings
    result = ok("rules", *(arg for path in checked for arg in ("--check", str(path))))
    assert result.output.startswith(f"ok: no violations in {len(checked)} file(s)")

    # 2. Frontend: pages <= 50 lines; every generated .tsx parses.
    tsx = [project / rel for rel in changed if rel.endswith(".tsx")]
    assert {p.parent.name for p in tsx} == {"pages", "components", "src"}
    for path in tsx:
        if path.parent.name == "pages":
            assert path.read_text().count("\n") <= 50, path
        assert _balanced(path.read_text()), path
    typescript = _typescript()
    if typescript is not None:
        node, compiler = typescript
        parsed = subprocess.run(
            [node, "-e", TS_PARSE, str(compiler), *map(str, tsx)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert parsed.returncode == 0, parsed.stdout + parsed.stderr
    _frontend_toolchain(project, [p.relative_to(project / "frontend") for p in tsx])

    # 3. Python: ruff (the project's defaults + a strict selection) and ruff format.
    if not _ruff_available():
        pytest.skip("ruff is not installed in this interpreter")
    module = "modules/karni-live-chat/"
    py = [rel for rel in changed if rel.endswith(".py") and not rel.startswith(module)]
    for args in (
        ["check", "--isolated", "--target-version", "py312", *py],
        ["check", "--isolated", "--target-version", "py312", "--extend-select",
         "E,W,F,I,UP,B,RUF", *py],
        ["format", "--isolated", "--check", *py],
    ):  # fmt: skip
        proc = _ruff(project, *args)
        assert proc.returncode == 0, f"ruff {args[0]}:\n{proc.stdout}{proc.stderr}"
    # The module carries its own [tool.ruff]; check it under that config.
    for args in (["check", "."], ["format", "--check", "."]):
        proc = _ruff(project / module, *args)
        assert proc.returncode == 0, f"ruff {args[0]} (module):\n{proc.stdout}{proc.stderr}"


def _frontend_toolchain(project: Path, files: list[Path]) -> None:
    """tsc + ESLint (karni/* rules) when KARNI_TEST_NODE_MODULES has the scaffold's deps."""
    modules = os.environ.get("KARNI_TEST_NODE_MODULES")
    node = shutil.which("node")
    if not modules or node is None:
        return
    frontend = project / "frontend"
    (frontend / "node_modules").symlink_to(Path(modules).resolve(), target_is_directory=True)
    for command in (
        [node, "node_modules/typescript/bin/tsc", "--noEmit", "-p", "."],
        [node, "node_modules/eslint/bin/eslint.js", *map(str, files)],
    ):
        proc = subprocess.run(command, cwd=frontend, text=True, capture_output=True, check=False)
        assert proc.returncode == 0, f"{command[1]}:\n{proc.stdout}{proc.stderr}"


# the generated backend, for real

VERIFY = """
import os
import uuid

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from rest_framework.test import APIClient

from events.models import Event, Venue
from karni.schedule import describe_schedules

User = get_user_model()
alice = User.objects.create_user(email="alice@example.com", password="pw-1234567890")
bob = User.objects.create_user(email="bob@example.com", password="pw-1234567890")
staff = User.objects.create_user(email="staff@example.com", password="pw-1234567890")
staff.groups.add(Group.objects.get_or_create(name="staff")[0])

assert APIClient().get("/api/events/").status_code == 401

client = APIClient()
client.force_authenticate(alice)
payload = {
    "title": "Launch",
    "starts_at": "2026-11-01T18:00:00Z",
    "status": "published",
    "capacity": 120,
    "organizer": str(bob.pk),
}
response = client.post("/api/events/", payload, format="json")
assert response.status_code == 201, response.content
event = Event.objects.get(pk=response.json()["id"])
assert event.organizer_id == alice.pk, "Owned('organizer') stamps the owner server-side"

venue = Venue.objects.create(name="Hall")
response = client.post("/api/events/", {**payload, "venue": str(venue.pk)}, format="json")
assert response.status_code == 400, "a staff-only venue is outside alice's read scope"

assert client.get("/api/events/?search=Laun").json()["count"] == 1
other = APIClient()
other.force_authenticate(bob)
assert other.get("/api/events/").json()["count"] == 0
assert other.get(f"/api/events/{event.pk}/").status_code == 404
assert client.patch(f"/api/events/{event.pk}/", {"capacity": 150}, format="json").status_code == 200

assert client.get("/api/venues/").status_code == 403
staff_client = APIClient()
staff_client.force_authenticate(staff)
response = staff_client.get("/api/venues/")
assert response.status_code == 200 and response.json()["count"] == 1

assert client.delete(f"/api/events/{event.pk}/").status_code == 204

# lifecycle and capacity: the generated StateField / CapacityField hold
from django.db import transaction
from events.models import Order
from karni.capacity import CapacityExceeded, reserve

created = client.post("/api/orders/", {"title": "First", "seats": 2}, format="json")
assert created.status_code == 201, created.content
assert created.json()["status"] == "draft" and created.json()["left"] == 2, created.json()
order_url = f"/api/orders/{created.json()['id']}/"
refused = client.patch(order_url, {"status": "refunded"}, format="json")
assert refused.status_code == 400 and refused.json()["status"][0].startswith("E980"), refused.content
assert client.patch(order_url, {"status": "confirmed"}, format="json").status_code == 200
order = Order.objects.get(pk=created.json()["id"])
with transaction.atomic():
    reserve(order, 2)
try:
    with transaction.atomic():
        reserve(order, 1)
except CapacityExceeded:
    pass
else:
    raise SystemExit("oversold")
assert post_save.has_listeners(Event)
assert "events.middleware.RequestTimingMiddleware" in settings.MIDDLEWARE
names = {row["name"] for row in describe_schedules()}
assert {"nightly-report", "digest"} <= names, names
print("generated backend OK")
"""

OVERLAY = '''"""Test overlay: sqlite, locmem cache, eager Celery — no services needed."""

from config.settings import *  # noqa: F403

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
'''


def _karni_importable() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("karni", "django"))


def _project_interpreter(project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A .venv whose python is this test's interpreter, on SQLite with the test overlay."""
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    (project / "config" / "test_overlay.py").write_text(OVERLAY)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.test_overlay")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite3'}")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path / "static"))
    monkeypatch.setenv("DEBUG", "True")
    return python


ROOT_PAGE = """
import django

django.setup()

from django.conf import settings
from django.test import Client
from django.test.utils import setup_test_environment

setup_test_environment()
assert settings.DEBUG, "the welcome page is mounted only while DEBUG is on"
body = Client().get("/").content.decode()
print("WELCOME" if "Karni is running" in body else "SITE" if "<h1>Website</h1>" in body else body)
"""

SITE_PAGES = """
import django

django.setup()

from django.test import Client
from django.test.utils import override_settings, setup_test_environment
from django.urls import reverse

setup_test_environment()
assert reverse("website:about") == "/about/"
assert Client().get("/about/").status_code == 200
assert "slug: design" in Client().get("/services/design/").content.decode()
with override_settings(DEBUG=False, ALLOWED_HOSTS=["*"]):
    missing = Client().get("/no-such-page/")
    assert missing.status_code == 404 and b"Page not found" in missing.content
print("site pages OK")
"""


@pytest.mark.skipif(not _karni_importable(), reason="needs karni + Django in this interpreter")
def test_a_site_app_replaces_the_welcome_page(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scaffold answers "/" with the welcome page until `karni make site` claims it."""
    require_modules("karni-site")  # the site app loads its runtime from it
    python = _project_interpreter(project, tmp_path, monkeypatch)
    ok("migrate")

    def run(script: str) -> str:
        proc = subprocess.run(
            [str(python), "-c", textwrap.dedent(script)],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(project)},
        )
        assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
        return proc.stdout.strip().splitlines()[-1]

    assert run(ROOT_PAGE) == "WELCOME"
    ok("make", "site", "website")
    ok("make", "view", "about")
    ok("make", "view", "service", "--path", "/services/<slug:slug>/")
    assert run(ROOT_PAGE) == "SITE"
    assert run(SITE_PAGES) == "site pages OK"
    ok("manage", "check")

    def page_test() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "website/tests"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )

    # The page test `karni make site` wrote passes: assert_pages on "/" and "/about/"
    # (`karni make view` added it), their links and stylesheet, and an unknown URL's 404.
    pages = (project / "website" / "tests" / "test_pages.py").read_text()
    assert 'PAGES = [\n    "/",\n    "/about/",\n    # karni:pages\n]' in pages
    tests = page_test()
    assert tests.returncode == 0, tests.stdout[-3000:] + tests.stderr[-3000:]

    # It fails, naming the page and the problem, when a page loses its title, its
    # description or an image's alt text, or links to a page that does not exist.
    site = project / "website"
    (site / "static" / "website" / "team.svg").write_text("<svg></svg>\n")
    about = site / "templates" / "website" / "about.html"
    about.write_text(
        about.read_text()
        .replace("{% block title %}About{% endblock %}", "{% block title %}{% endblock %}")
        .replace("<h1>About</h1>\n", '<h1>About</h1>\n  <img src="/static/website/team.svg">\n')
    )
    home = site / "templates" / "website" / "home.html"
    text = re.sub(r"\{% block description %\}.*?\{% endblock %\}\n", "", home.read_text())
    home.write_text(text.replace("<h1>Website</h1>\n", '<h1>Website</h1>\n  <a href="/x/">X</a>\n'))
    tests = page_test()
    output = tests.stdout + tests.stderr
    assert tests.returncode == 1, output[-3000:]
    for line in (
        "E618: assert_pages: 4 problem(s) (2 page(s) and 5 link(s) checked)",
        '  - /: a <meta name="description"> with an empty content attribute. ',
        "  - /about/: an empty <title>. ",
        "  - /about/: 1 <img> without an alt attribute: /static/website/team.svg (line ",
        "  - /: links to /x/ (line ",
    ):
        assert line in output, output[-3000:]


IMPORTED_SITE = """
import django

django.setup()

from django.test import Client, override_settings
from django.test.utils import setup_test_environment
from karni.security import script_hash

setup_test_environment()
with override_settings(DEBUG=False, ALLOWED_HOSTS=["*"]):
    client = Client()
    home = client.get("/")
    assert home.status_code == 200, home.status_code
    page = home.content.decode()
    # The design's markup, with the current menu item marked as the designer did.
    assert '<a href="/" class="active">Home</a>' in page, page
    assert '<a href="/about/">About</a>' in page
    assert '<section class="hero" style="background-image: url(&quot;/static/website/img/hero.jpg&quot;)">' in page
    assert '<script>document.documentElement.classList.add("js");</script>' in page
    policy = home.headers["Content-Security-Policy"]
    assert script_hash('document.documentElement.classList.add("js");') in policy, policy
    assert "https://fonts.googleapis.com" in policy and "https://fonts.gstatic.com" in policy
    about = client.get("/about/").content.decode()
    assert '<a href="/about/" class="active">About</a>' in about
    assert "<code>{{ flour }} + {{ water }}</code>" in about
    contact = client.get("/contact/")
    assert 'onclick="history.back()"' in contact.content.decode()
    contact_policy = contact.headers["Content-Security-Policy"]
    assert "'unsafe-hashes'" in contact_policy and script_hash("history.back()") in contact_policy
    assert "form-action 'self' https://forms.example.com" in contact_policy
    moved = client.get("/specials/?week=12")
    assert (moved.status_code, moved["Location"]) == (301, "/menu/?week=12"), moved["Location"]
    missing = client.get("/no-such-page/")
    assert missing.status_code == 404
    # karni_site renders the site's 404 page with the request: the layout is there.
    assert b"Page not found" in missing.content and b'<header class="top">' in missing.content
print("imported site OK")
"""


@pytest.mark.skipif(not _karni_importable(), reason="needs karni + Django in this interpreter")
def test_an_imported_design_runs_for_real(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`karni import design` on the bakery fixture: the pages, the policy, the redirect."""
    require_modules("karni-site")
    python = _project_interpreter(project, tmp_path, monkeypatch)
    ok("migrate")
    result = ok("import", "design", str(DESIGNS / "bakery"), "--app", "website")
    assert "imported 4 page(s), 1 redirect(s), 0 partial(s), 7 file(s) copied." in result.output
    # The module is importable through the project interpreter, so its guidance is recorded.
    assert (project / ".karni" / "modules" / "site.md").is_file()
    assert "<!-- karni:module:site -->" in (project / "AGENTS.md").read_text()
    ok("manage", "check")
    proc = subprocess.run(
        [str(python), "-c", textwrap.dedent(IMPORTED_SITE)],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(project)},
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    assert proc.stdout.strip().splitlines()[-1] == "imported site OK"
    tests = subprocess.run(
        [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "website/tests"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tests.returncode == 0, tests.stdout[-3000:] + tests.stderr[-3000:]
    # A page added later extends the imported layout and passes the same test.
    ok("make", "view", "team", "--app", "website")
    tests = subprocess.run(
        [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "website/tests"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tests.returncode == 0, tests.stdout[-3000:] + tests.stderr[-3000:]
    assert "karni check" not in tests.stdout


@pytest.mark.skipif(not _karni_importable(), reason="needs karni + Django in this interpreter")
def test_generated_backend_runs_for_real(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app + model + viewset + serializer + listener + schedule, migrated and served."""
    for args in (
        ["make", "app", "events"],
        ["make", "model", "Venue", "name:str:120"],
        ["make", "model", "Event", "title:str:200", "starts_at:datetime",
         "status:choice:draft|published", "organizer:fk:User", "venue:fk:Venue?",
         "capacity:int?", "--with", "viewset", "--access", "owned:organizer",
         "--search", "title"],
        ["make", "viewset", "Venue", "--access", "staff"],
        ["make", "model", "Product", "name:str:120", "slug:slug:name", "price:money:EUR",
         "cost:money", "rate:percent", "stock:quantity", "phone:phone?", "country:country?",
         "email:email:unique", "meta:json:queried", "--with", "viewset", "--access", "staff"],
        ["make", "model", "Order", "title:str:80",
         "status:state:draft>confirmed>refunded|draft>cancelled|confirmed>cancelled",
         "seats:int", "left:capacity:seats", "--with", "viewset", "--access", "authenticated",
         "--search", "title"],
        ["make", "serializer", "Venue", "--reason", "explicit field list"],
        ["make", "test", "Event"],
        ["make", "test", "Order"],
        ["make", "test", "Venue"],
        ["make", "seeder", "Venue", "--count", "4"],
        ["make", "factory", "Event"],
        ["make", "listener", "stamp_event", "--on", "Event.created"],
        ["make", "listener", "sync_event", "--on", "Event.updated", "--queued"],
        ["make", "schedule", "nightly-report", "--cron", "0 3 * * *"],
        ["make", "schedule", "digest", "--every", "15m", "--task", "events.tasks.nightly_report"],
        ["make", "middleware", "RequestTiming"],
    ):  # fmt: skip
        ok(*args)
    # The project interpreter: a .venv whose python is this test's interpreter.
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    (project / "config" / "test_overlay.py").write_text(OVERLAY)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.test_overlay")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'db.sqlite3'}")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path / "static"))

    ok("make", "migration")
    assert (project / "events" / "migrations" / "0001_initial.py").is_file()
    ok("migrate")
    ok("manage", "check")
    # karni schema explains what the typed fields created, read back from the database.
    described = ok("schema", "events.Product")
    assert 'LOWER("email")' in described.output and "[ok] constraint" in described.output
    assert "why: QuantityField: integer, CHECK >= 0" in described.output
    verify = subprocess.run(
        [str(python), "-c", textwrap.dedent(VERIFY)],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(project)},
    )
    assert verify.returncode == 0, verify.stdout[-3000:] + verify.stderr[-3000:]
    assert "generated backend OK" in verify.stdout

    # karni seed fills every model (the seeder pins Venue at 4) and prints the demo login.
    # The check above left rows behind, so seed needs --force to add demo rows on top (E617).
    seeded = subprocess.run(
        [
            str(python),
            "manage.py",
            "karni_seed",
            "--count",
            "6",
            "--seed",
            "42",
            "--json",
            "--force",
        ],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert seeded.returncode == 0, seeded.stdout[-3000:] + seeded.stderr[-3000:]
    report = json.loads(seeded.stdout)
    assert report["rows"]["events.Event"] == 6 and report["rows"]["events.Venue"] == 4
    assert report["rows"]["events.Product"] == 6  # ISO codes, E.164, bounds: CHECKs accept them
    assert report["demo"] == "demo@example.com" and "staff" in report["roles"]

    # The API tests `karni make test` wrote pass: CRUD surface + owner isolation.
    tests = subprocess.run(
        [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "events/tests"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tests.returncode == 0, tests.stdout[-4000:] + tests.stderr[-3000:]
    # Event: crud + isolation; Venue; Order (StateField + CapacityField): crud
    assert "4 passed" in tests.stdout, tests.stdout[-2000:]

    # A generated module's standalone suite passes too, even inside a project tree.
    if importlib.util.find_spec("pytest_django") is not None:
        ok("make", "module", "live-chat")
        env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
        suite = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=project / "modules" / "karni-live-chat",
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert suite.returncode == 0, suite.stdout[-3000:] + suite.stderr[-3000:]
