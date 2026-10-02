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
   the generated endpoints with the Django test client, and run a generated
   module's standalone test suite.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import agent_data
from karni_cli.main import app

from .conftest import REPO_ROOT, TEMPLATE
from .test_make import GENERATORS, ok, snapshot

#: Every generator, both spellings, the chains, every --access / --on shape.
SEQUENCE: list[list[str]] = [
    ["make", "app", "events"],
    ["make:app", "shop"],
    ["make", "model", "Tag", "label:slug", "--app", "shop", "--with", "viewset",
     "--access", "public-read"],
    ["make", "model", "Venue", "name:str:120", "city:str?", "--app", "events"],
    ["make:model", "Event", "title:str:200", "body:text?", "starts_at:datetime",
     "day:date?", "status:choice:draft|published|in-review", "organizer:fk:User",
     "venue:fk:Venue?", "capacity:int?", "ratio:float?", "price:decimal:8:2?",
     "is_open:bool", "contact:email?", "site:url?", "code:slug:40?", "meta:json",
     "ref:uuid", "doc:file?", "photo:image?", "tags:m2m:shop.Tag?", "profile:o2o:User?",
     "--app", "events", "-a", "--access", "owned:organizer", "--search", "title,status"],
    ["make", "viewset", "Venue", "--app", "events", "--access", "staff"],
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


# --- the generated backend, for real -------------------------------------------------------

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
        ["make", "serializer", "Venue", "--reason", "explicit field list"],
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
