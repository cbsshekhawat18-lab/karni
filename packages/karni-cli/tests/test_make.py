"""``karni make``: the universal generator behaviour and each generator's contract.

The quality gate (every generator's output is lint- and rules-clean, and the
generated backend really runs) lives in ``test_make_gate.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from karni_cli import project as project_mod
from karni_cli.main import app

from .conftest import TEMPLATE

GENERATORS = {
    "app",
    "model",
    "viewset",
    "serializer",
    "migration",
    "test",
    "factory",
    "seeder",
    "task",
    "schedule",
    "event",
    "listener",
    "command",
    "service",
    "middleware",
    "page",
    "component",
    "module",
}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh ``karni new`` project; the cwd is inside it."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Make Check", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "make_check"
    monkeypatch.chdir(root)
    return root


def run(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def ok(*args: str) -> Result:
    result = run(*args)
    assert result.exit_code == 0, f"{args}: {result.output}\n{result.exception!r}"
    return result


def fails(*args: str, match: str) -> str:
    result = run(*args)
    assert result.exit_code != 0, result.output
    message = str(result.exception) if result.exception else result.output
    assert match in message, message
    return message


def snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and "node_modules" not in p.parts
    }


# discovery


def test_list_prints_every_generator_and_only_those() -> None:
    result = ok("make", "--list")
    names = {line.split()[0] for line in result.output.strip().splitlines()}
    assert names == GENERATORS


def test_make_without_a_type_prints_help() -> None:
    result = ok("make")
    assert "--list" in result.output and "model" in result.output


def test_aliases_are_hidden_but_work(project: Path) -> None:
    assert "make:model" not in ok("--help").output
    ok("make:app", "events")
    ok("make:task", "via_alias")
    ok("make", "task", "via_group")
    tasks = (project / "events" / "tasks.py").read_text()
    assert "def via_alias() -> None:" in tasks and "def via_group() -> None:" in tasks


# universal behaviour


def test_app_wires_settings_and_writes_only_the_contract_files(project: Path) -> None:
    result = ok("make", "app", "events")
    created = sorted(p.relative_to(project).as_posix() for p in (project / "events").rglob("*"))
    assert created == [
        "events/__init__.py",
        "events/apps.py",
        "events/migrations",
        "events/migrations/__init__.py",
        "events/models.py",
        "events/tests",
        "events/tests/__init__.py",
        "events/viewsets.py",
    ]
    assert '    "events",\n]  # karni:apps' in (project / "config" / "settings.py").read_text()
    assert "created  events/apps.py" in result.output
    assert "modified config/settings.py" in result.output


def test_never_overwrites_without_force(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "task", "digest")
    before = (project / "events" / "tasks.py").read_text()
    fails("make", "task", "digest", match="--force")
    assert (project / "events" / "tasks.py").read_text() == before
    ok("make", "task", "digest", "--retry", "2", "--force")
    after = (project / "events" / "tasks.py").read_text()
    assert after.count("def digest(") == 1 and "max_retries=2" in after
    fails("make", "app", "events", match="pass --force to create only the missing files")
    # --force on a skeleton fills in missing files and never truncates existing ones.
    models = project / "events" / "models.py"
    (project / "events" / "apps.py").unlink()
    models.write_text(models.read_text() + "# user code\n")
    result = ok("make", "app", "events", "--force")
    assert (project / "events" / "apps.py").is_file()
    assert models.read_text().endswith("# user code\n")
    assert "kept     events/models.py (exists)" in result.output


def test_dry_run_writes_nothing_and_shows_the_diff(project: Path) -> None:
    ok("make", "app", "events")
    before = snapshot(project)
    result = ok("make", "model", "Event", "title:str", "--with", "viewset", "--dry-run")
    assert snapshot(project) == before
    assert "would modify events/models.py" in result.output
    assert "+class Event(BaseModel):" in result.output
    assert "(dry run: nothing written)" in result.output


def test_failed_step_writes_nothing(project: Path) -> None:
    ok("make", "app", "events")
    before = snapshot(project)
    fails("make", "model", "Event", "title:str", "tags:m2m:Missing", "-a", match="Missing")
    assert snapshot(project) == before


def test_app_resolution(project: Path) -> None:
    fails("make", "task", "digest", match="no local app yet")
    ok("make", "app", "events")
    ok("make", "task", "digest")  # the only local app is the default
    ok("make", "app", "shop")
    fails("make", "task", "other", match="Several local apps (events, shop)")
    fails("make", "task", "other", "--app", "nope", match="local apps: events, shop")
    ok("make", "task", "other", "--app", "shop")
    assert "def other()" in (project / "shop" / "tasks.py").read_text()


def test_app_name_rules(project: Path) -> None:
    fails("make", "app", "Events", match="snake_case")
    fails("make", "app", "json", match="shadow")
    fails("make", "app", "karni_x", match="karni make module")


# model / viewset / serializer


def test_model_chain_and_access_default_is_announced(project: Path) -> None:
    ok("make", "app", "events")
    result = ok("make", "model", "Event", "title:str:200", "--with", "viewset", "--search", "title")
    assert "access: Granted() — the default: what KARNI_ROLES grants for Event" in result.output
    assert "next: karni make migration --app events" in result.output
    viewsets = (project / "events" / "viewsets.py").read_text()
    assert "access = Granted()" in viewsets
    assert "from karni.api import BaseViewSet, Granted" in viewsets
    assert 'search_fields = ("title",)' in viewsets


@pytest.mark.parametrize(
    ("access", "declaration"),
    [
        ("granted", "Granted()"),
        ("authenticated", "Access(read=Authenticated(), write=Authenticated())"),
        ("public-read", "Access(read=Public(), write=Authenticated())"),
        ("owned:owner", 'Access(read=Owned("owner"), write=Owned("owner"))'),
        ("staff", 'Access(read=HasRole("staff"), write=HasRole("staff"))'),
        ("role:editor", 'Access(read=HasRole("editor"), write=HasRole("editor"))'),
    ],
)
def test_viewset_access_choices(project: Path, access: str, declaration: str) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "owner:fk:User")
    ok("make", "viewset", "Event", "--access", access)
    assert f"access = {declaration}" in (project / "events" / "viewsets.py").read_text()


def test_viewset_validation(project: Path) -> None:
    ok("make", "app", "events")
    fails("make", "viewset", "Event", match="create it first: karni make model Event")
    ok("make", "model", "Event", "title:str")
    fails("make", "viewset", "Event", "--access", "owned:title", match="not a relation")
    fails("make", "viewset", "Event", "--access", "everyone", match="choose one of")
    fails("make", "viewset", "Event", "--search", "nope", match="has no field 'nope'")
    fails("make", "model", "Other", "--access", "staff", match="--with viewset")


def test_model_force_replaces_only_that_class(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    ok("make", "model", "Event", "title:str", "venue:fk:Venue")
    fails("make", "model", "Event", "title:str", match="--force")
    ok("make", "model", "Event", "name:str", "--force")
    models = (project / "events" / "models.py").read_text()
    assert models.count("class Event(BaseModel):") == 1
    assert "class Venue(BaseModel):" in models and "venue = " not in models


def test_serializer_needs_a_reason_and_wires_the_viewset(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "owner:fk:User")
    fails("make", "serializer", "Event", "--reason", "x", match="No viewset for Event")
    ok("make", "viewset", "Event", "--access", "owned:owner")
    fails("make", "serializer", "Event", match="--reason is required")
    result = ok("make", "serializer", "Event", "--reason", "computed label")
    assert "generates a serializer already" in result.output
    serializers = (project / "events" / "serializers.py").read_text()
    assert "# karni: allow(redundant-serializer): computed label" in serializers
    assert '"owner",\n        )' in serializers  # the owner field is read-only
    viewsets = (project / "events" / "viewsets.py").read_text()
    assert "    model = Event\n    serializer_class = EventSerializer\n" in viewsets
    assert "from events.serializers import EventSerializer" in viewsets


# test / factory / seeder


def test_test_generator_follows_the_viewset(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "organizer:fk:User")
    fails("make", "test", "Event", match="create it first: karni make viewset Event")
    ok("make", "viewset", "Event", "--access", "owned:organizer")
    result = ok("make", "test", "Event")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert "from events.viewsets import EventViewSet" in text
    assert "        self.assert_crud(EventViewSet)\n" in text
    assert "        self.assert_isolated(EventViewSet)\n" in text
    assert "as any signed-in user + owner isolation" in result.output
    assert "run: karni test events/tests/test_event.py" in result.output
    fails("make", "test", "Event", match="--force")
    ok("make", "test", "Event", "--role", "organizer", "--force")
    assert (
        'self.assert_crud(EventViewSet, "organizer")'
        in (project / "events" / "tests" / "test_event.py").read_text()
    )


def test_test_generator_picks_a_granted_role(project: Path) -> None:
    """A Granted() viewset is tested as the first KARNI_ROLES role with a scoped grant."""
    ok("make", "app", "events")
    result = ok("make", "model", "Event", "title:str", "--with", "viewset,test")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert '        self.assert_crud(EventViewSet, "user")\n' in text  # shipped: user = own
    assert '        self.assert_isolated(EventViewSet, "user")\n' in text
    assert "as role 'user' + grant isolation" in result.output
    settings = project / "config" / "settings.py"
    settings.write_text(
        settings.read_text()
        + '\nKARNI_ROLES = {"ops": {"grants": {"*": "all"}}, "clerk": {"grants": {"events.*": "own"}}}\n'
    )
    result = ok("make", "test", "Event", "--force")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert '        self.assert_crud(EventViewSet, "clerk")\n' in text
    assert "        self.assert_isolated(EventViewSet" in text
    result = ok("make", "test", "Event", "--role", "ops", "--force")
    text = (project / "events" / "tests" / "test_event.py").read_text()
    assert '        self.assert_crud(EventViewSet, "ops")\n' in text
    assert "assert_isolated" not in text  # an `all` grant partitions nothing
    assert "as role 'ops'" in result.output and "isolation" not in result.output


def test_test_generator_takes_the_declared_role(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str", "--with", "viewset,test", "--access", "staff")
    text = (project / "events" / "tests" / "test_venue.py").read_text()
    assert 'self.assert_crud(VenueViewSet, "staff")' in text
    assert "assert_isolated" not in text  # nothing Owned: no isolation test


def test_factory_and_seeder_generators(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    ok("make", "model", "Event", "title:str", "--with", "factory,seeder")
    ok("make", "factory", "Venue")
    ok("make:seeder", "Venue", "--count", "0")
    factories = (project / "events" / "factories.py").read_text()
    assert "from karni.testing.factories import ModelFactory" in factories
    assert "class EventFactory(ModelFactory):" in factories
    assert "class VenueFactory(ModelFactory):" in factories
    assert factories.count("        model = ") == 2
    seeds = (project / "events" / "seeds.py").read_text()
    assert "from karni.seeding import Seeder" in seeds
    assert "class EventSeeder(Seeder):" in seeds
    assert "        model = Venue\n        count = 0\n" in seeds
    fails("make", "factory", "Venue", match="--force")
    fails("make", "seeder", "Nope", match="create it first")
    fails("make", "seeder", "Venue", "--count", "-1", "--force", match="0 or more")


def test_all_chains_the_test_but_not_the_overrides(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "-a")
    assert (project / "events" / "tests" / "test_event.py").is_file()
    assert not (project / "events" / "factories.py").exists()
    assert not (project / "events" / "seeds.py").exists()
    fails("make", "model", "Other", "--with", "nope", match="available: viewset, page, test")


# tasks, schedules, events, listeners


def test_schedule(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "app", "shop")
    fails("make", "schedule", "nightly", "--app", "events", match="exactly one of")
    fails("make", "schedule", "nightly", "--every", "15x", "--app", "events", match="--every")
    fails("make", "schedule", "x", "--cron", "0 3 *", "--app", "events", match="5 fields")
    ok("make", "schedule", "nightly-report", "--cron", "0 3 * * *", "--app", "events")
    schedules = (project / "events" / "schedules.py").read_text()
    assert 'cron("0 3 * * *", tasks.nightly_report, name="nightly-report")' in schedules
    assert "def nightly_report() -> None:" in (project / "events" / "tasks.py").read_text()
    fails("make", "schedule", "nightly-report", "--every", "1h", "--app", "shop", match="already")
    fails(
        "make", "schedule", "x", "--every", "1h", "--task", "events.tasks.nope", "--app", "events",
        match="No task nope",
    )  # fmt: skip
    ok("make", "schedule", "nightly-report", "--every", "1h", "--app", "events", "--force")
    schedules = (project / "events" / "schedules.py").read_text()
    assert 'every("1h", tasks.nightly_report, name="nightly-report")' in schedules
    assert "cron(" not in schedules.split("import")[-1]


def test_listener_variants(project: Path) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str")
    fails("make", "listener", "x", "--on", "Event.renamed", match="expected Model.created")
    fails("make", "listener", "x", "--on", "Venue.created", match="no model Venue")
    fails("make", "listener", "x", "--on", "order_shipped", match="karni make event")
    ok("make", "listener", "sync", "--on", "Event.updated", "--queued")
    # An installed app's model, and the user model: the lazy "app_label.Model" form.
    ok("make", "listener", "confirm_paid", "--on", "karni_payments.Payment.updated")
    ok("make", "listener", "welcome", "--on", "User.created")
    ok("make", "event", "order_shipped")
    ok("make", "listener", "notify", "--on", "order_shipped", "--queued")
    listeners = (project / "events" / "listeners.py").read_text()
    assert "@on_updated(Event, queued=True)\ndef sync(event: Event) -> None:" in listeners
    assert '@on_updated("karni_payments.Payment")\ndef confirm_paid(payment: Any)' in listeners
    assert '@on_created("karni_accounts.User")\ndef welcome(user: Any)' in listeners
    assert "from typing import Any" in listeners and "karni_payments" not in listeners.split("@")[0]
    assert "@receiver(order_shipped)" in listeners
    assert "transaction.on_commit(tasks.notify.delay)" in listeners
    assert "def notify() -> None:" in (project / "events" / "tasks.py").read_text()


def test_command_service_middleware(project: Path) -> None:
    ok("make", "app", "events")
    fails("make", "command", "migrate", match="Django/Karni command")
    ok("make", "command", "send_reminders")
    assert (project / "events" / "management" / "commands" / "__init__.py").is_file()
    ok("make", "service", "stripe_client")
    assert (
        "class StripeClientService:"
        in (project / "events" / "services" / "stripe_client.py").read_text()
    )
    result = ok("make", "middleware", "RequestTiming")
    assert "events.middleware.RequestTimingMiddleware" in result.output
    settings = (project / "config" / "settings.py").read_text()
    assert '    "events.middleware.RequestTimingMiddleware",\n]  # karni:middleware' in settings


def test_middleware_without_marker_prints_the_manual_step(project: Path) -> None:
    ok("make", "app", "events")
    settings = project / "config" / "settings.py"
    settings.write_text(settings.read_text().replace("# karni:middleware", "# (removed)"))
    result = ok("make", "middleware", "Audit")
    assert "wire it yourself: add 'events.middleware.AuditMiddleware' to MIDDLEWARE" in (
        result.output
    )


# frontend


def test_pages_link_only_to_routes_that_exist(project: Path) -> None:
    pages = project / "frontend" / "src" / "pages"
    ok("make", "page", "events", "--resource", "events")
    assert "navigate" not in (pages / "events.tsx").read_text()  # no detail/form route yet
    ok("make", "page", "event-detail", "--resource", "events", "--kind", "detail")
    ok("make", "page", "events", "--resource", "events", "--force")
    listing = (pages / "events.tsx").read_text()
    assert 'to: "/events/$id"' in listing and "/events/new" not in listing
    routes = (project / "frontend" / "src" / "routes.tsx").read_text()
    assert routes.count('path: "/events"') == 1  # --force did not duplicate the route
    assert 'import EventDetailPage from "./pages/event-detail";' in routes
    fails("make", "page", "other", "--path", "/events", match="already registered")
    # The sign-in page: @karni/ui's LoginForm, no resource needed.
    result = ok("make", "page", "login", "--kind", "login")
    assert "page: /login -> LoginPage" in result.output
    login = (project / "frontend" / "src" / "pages" / "login.tsx").read_text()
    assert 'import { LoginForm, Page } from "@karni/ui";' in login
    assert '<LoginForm onSuccess={() => void navigate({ to: "/" })} />' in login
    assert '<Page title="Sign in">' in login
    fails("make", "page", "x", "--kind", "list", match="needs --resource")
    fails("make", "page", "Bad_Name", match="kebab-case")
    fails("make", "page", "x", "--title", 'Say "hi"', match="plain text only")


def test_page_without_route_markers(project: Path) -> None:
    (project / "frontend" / "src" / "routes.tsx").write_text("export const routes = [];\n")
    fails("make", "page", "reports", match="--no-route")
    result = ok("make", "page", "reports", "--no-route")
    assert "route not registered (--no-route)" in result.output
    assert (project / "frontend" / "src" / "pages" / "reports.tsx").is_file()


def test_component_roles(project: Path) -> None:
    manifest = project / "frontend" / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"roles": {"data-table": "ResourceTable"}}))
    result = ok("make", "component", "StatusBadge")
    assert (
        'registerComponentRole("status-badge", "StatusBadge");'
        in (project / "frontend" / "src" / "components" / "StatusBadge.tsx").read_text()
    )
    assert "role: status-badge" in result.output
    fails("make", "component", "MyTable", "--role", "data-table", match="@karni/ui's ResourceTable")
    fails("make", "component", "Badge2", "--role", "status-badge", match="StatusBadge (")
    ok("make", "component", "MyTable", "--role", "data-table", "--replace-reason", "virtualised")
    source = (project / "frontend" / "src" / "components" / "MyTable.tsx").read_text()
    assert '{ replace: true, reason: "virtualised" }' in source


# module


def test_module_outside_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = ok("make", "module", "live-chat")
    root = tmp_path / "modules" / "karni-live-chat"
    assert "created  modules/karni-live-chat/karni_live_chat/apps.py" in result.output
    pyproject = (root / "pyproject.toml").read_text()
    assert 'name = "karni-live-chat"' in pyproject
    assert 'live_chat = "karni_live_chat.conf:DEFAULTS"' in pyproject
    assert 'dependencies = ["karni>=0.' in pyproject
    assert (root / "karni_live_chat" / "AGENTS.fragment.md").is_file()
    assert 'label = "karni_live_chat"' in (root / "karni_live_chat" / "apps.py").read_text()
    fails("make", "module", "karni-chat", match="prefix")


# migration (through the project interpreter)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


@pytest.fixture
def recorder(project: Path, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    rec = Recorder()
    monkeypatch.setattr(project_mod, "run_process", rec)
    return rec


def test_migration_wraps_makemigrations(project: Path, recorder: Recorder) -> None:
    ok("make", "app", "events")
    python = str(project / ".venv" / "bin" / "python")
    ok("make", "migration")
    ok("make", "migration", "add_capacity", "--app", "events", "--dry-run")
    ok("make", "migration", "backfill", "--empty")
    ok("make:migration")
    assert recorder.calls == [
        [python, "manage.py", "makemigrations"],
        [python, "manage.py", "makemigrations", "events", "--name", "add_capacity", "--dry-run"],
        [python, "manage.py", "makemigrations", "events", "--name", "backfill", "--empty"],
        [python, "manage.py", "makemigrations"],
    ]


def test_model_migrate_flag_runs_makemigrations(project: Path, recorder: Recorder) -> None:
    ok("make", "app", "events")
    ok("make", "model", "Event", "title:str", "--migrate")
    assert recorder.calls == [
        [str(project / ".venv" / "bin" / "python"), "manage.py", "makemigrations", "events"]
    ]


def test_detail_pages_expand_the_model_relations(project: Path) -> None:
    """Relations render as labels, not raw ids (audit item 16); user FKs stay ids."""
    ok("make", "app", "events")
    ok("make", "model", "Venue", "name:str")
    ok("make", "model", "Show", "title:str", "venue:fk:Venue", "organizer:fk:User", "-a")
    page = (project / "frontend" / "src" / "pages" / "show-detail.tsx").read_text()
    assert 'expand={["venue"]}' in page
