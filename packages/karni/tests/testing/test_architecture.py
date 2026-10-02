"""Tests for karni.testing.architecture — positive, negative and opt-out paths."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.db import models
from django.test.utils import isolate_apps

from karni.testing import _source, architecture
from karni.testing._source import Violation, check_optout


def fake_app(tmp_path: Path, files: dict[str, str]) -> SimpleNamespace:
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return SimpleNamespace(path=str(tmp_path), name="fakeapp", label="fakeapp")


@pytest.fixture
def as_project(monkeypatch):
    """Point project-app discovery at a fake app directory."""

    def _install(cfg):
        monkeypatch.setattr(_source, "project_app_configs", lambda: [cfg])
        monkeypatch.setattr(architecture, "project_app_configs", lambda: [cfg])
        _source._file_lines.cache_clear()
        return cfg

    return _install


# --- opt-out semantics (F5) ---------------------------------------------------


def test_optout_with_reason_suppresses(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("do_thing()  # karni: allow(raw-sql): vendor requires literal SQL\n")
    _source._file_lines.cache_clear()
    v = Violation(rule="raw-sql", location="x.py:1", message="m")
    assert check_optout(f, "raw-sql", [1], v) == []


def test_optout_without_reason_reports_both(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("do_thing()  # karni: allow(raw-sql):\n")
    _source._file_lines.cache_clear()
    v = Violation(rule="raw-sql", location="x.py:1", message="m")
    out = check_optout(f, "raw-sql", [1], v)
    assert [x.rule for x in out] == ["opt-out-reason", "raw-sql"]


def test_optout_multiple_rules_one_marker(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text("y()  # karni: allow(raw-sql, http-client): shared edge\n")
    _source._file_lines.cache_clear()
    v = Violation(rule="http-client", location="x.py:1", message="m")
    assert check_optout(f, "http-client", [1], v) == []


# --- raw-sql ------------------------------------------------------------------

RAW_SQL = """
from django.db import connection

def report():
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
"""


def test_raw_sql_detected(tmp_path, as_project) -> None:
    as_project(fake_app(tmp_path, {"views.py": RAW_SQL}))
    violations = architecture.check_raw_sql()
    assert len(violations) == 1 and violations[0].rule == "raw-sql"


def test_raw_sql_allowed_dir(tmp_path, as_project) -> None:
    as_project(fake_app(tmp_path, {"sql/reports.py": RAW_SQL, "migrations/0001_x.py": RAW_SQL}))
    assert architecture.check_raw_sql() == []


def test_raw_sql_optout(tmp_path, as_project) -> None:
    content = RAW_SQL.replace(
        'cur.execute("SELECT 1")',
        'cur.execute("SELECT 1")  # karni: allow(raw-sql): aggregate too complex for ORM',
    )
    as_project(fake_app(tmp_path, {"views.py": content}))
    assert architecture.check_raw_sql() == []


# --- http-client --------------------------------------------------------------


def test_http_import_detected_and_services_allowed(tmp_path, as_project) -> None:
    as_project(
        fake_app(
            tmp_path,
            {
                "views.py": "import requests\n",
                "services/client.py": "import httpx\n",
                "tests/test_x.py": "import requests\n",
            },
        )
    )
    violations = architecture.check_http_client()
    assert len(violations) == 1
    assert "views.py" in violations[0].location


def test_http_from_import_detected(tmp_path, as_project) -> None:
    as_project(fake_app(tmp_path, {"views.py": "from urllib.request import urlopen\n"}))
    assert [v.rule for v in architecture.check_http_client()] == ["http-client"]


# --- model-base ---------------------------------------------------------------


@pytest.mark.django_db
def test_testapp_models_pass(monkeypatch) -> None:
    real = [django_apps.get_app_config("testapp")]
    monkeypatch.setattr(architecture, "project_app_configs", lambda: real)
    assert architecture.check_model_base() == []


@isolate_apps("tests.testapp")
def test_plain_model_flagged(monkeypatch) -> None:
    class Rogue(models.Model):  # noqa: DJ008
        class Meta:
            app_label = "testapp"

    cfg = SimpleNamespace(get_models=lambda: [Rogue], name="testapp", label="testapp")
    monkeypatch.setattr(architecture, "project_app_configs", lambda: [cfg])
    violations = architecture.check_model_base()
    assert len(violations) == 1 and "Rogue" in violations[0].message


# --- viewset-base -------------------------------------------------------------


@pytest.mark.django_db
def test_testapp_viewsets_pass(monkeypatch) -> None:
    real = [django_apps.get_app_config("testapp")]
    monkeypatch.setattr(architecture, "project_app_configs", lambda: real)
    assert architecture.check_viewset_base() == []


# --- viewset-access -----------------------------------------------------------

VIEWSETS = """
from karni.api import Access, Authenticated, BaseViewSet, Public
from tests.testapp.models import Event


class Declared(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Authenticated())


class Inherits(Declared):
    pass


class Dynamic(BaseViewSet):
    model = Event

    def get_access(self):
        return Access(read=Public(), write=Authenticated())


class AbstractBase(BaseViewSet):
    pass


class Forgotten(BaseViewSet):
    model = Event


# karni: allow(viewset-access): disabled endpoint, kept for URL stability
class OptedOut(BaseViewSet):
    model = Event


# karni: allow(viewset-access):
class NoReason(BaseViewSet):
    model = Event
"""


@pytest.fixture
def fake_viewsets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import VIEWSETS from a real file (class source must be retrievable)."""
    path = tmp_path / "fake_viewsets.py"
    path.write_text(VIEWSETS)
    spec = importlib.util.spec_from_file_location("fake_viewsets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "fake_viewsets", module)
    spec.loader.exec_module(module)
    _source._file_lines.cache_clear()
    classes = [obj for obj in vars(module).values() if isinstance(obj, type)]
    monkeypatch.setattr(architecture, "_viewset_candidates", lambda: classes)
    return module


def test_viewset_without_access_is_flagged(fake_viewsets: ModuleType) -> None:
    violations = architecture.check_viewset_access()
    flagged = sorted(v.message.split()[0] for v in violations if v.rule == "viewset-access")
    # Declared/Inherits/Dynamic declare access, AbstractBase has no model,
    # OptedOut carries a reasoned marker; NoReason's marker has no reason.
    assert flagged == ["Forgotten", "NoReason"]
    assert [v.rule for v in violations if v.rule == "opt-out-reason"] == ["opt-out-reason"]


@pytest.mark.django_db
def test_testapp_viewsets_declare_access(monkeypatch: pytest.MonkeyPatch) -> None:
    real = [django_apps.get_app_config("testapp")]
    monkeypatch.setattr(architecture, "project_app_configs", lambda: real)
    assert architecture.check_viewset_access() == []


# --- access-override ----------------------------------------------------------

OVERRIDE = """
class EventViewSet(BaseViewSet):
    model = Event

    def filter_queryset_for_user(self, queryset):
        return queryset
"""


def test_access_override_detected(tmp_path: Path, as_project) -> None:
    as_project(fake_app(tmp_path, {"viewsets.py": OVERRIDE}))
    violations = architecture.check_access_override()
    assert [v.rule for v in violations] == ["access-override"]
    assert violations[0].location.endswith("viewsets.py:5")


def test_access_override_optout(tmp_path: Path, as_project) -> None:
    content = OVERRIDE.replace(
        "    def filter_queryset_for_user",
        "    # karni: allow(access-override): rows depend on a subscription service\n"
        "    def filter_queryset_for_user",
    )
    as_project(fake_app(tmp_path, {"viewsets.py": content}))
    assert architecture.check_access_override() == []


def test_access_override_optout_needs_a_reason(tmp_path: Path, as_project) -> None:
    content = OVERRIDE.replace(
        "    def filter_queryset_for_user(self, queryset):",
        "    def filter_queryset_for_user(self, queryset):  # karni: allow(access-override):",
    )
    as_project(fake_app(tmp_path, {"viewsets.py": content}))
    rules = [v.rule for v in architecture.check_access_override()]
    assert rules == ["opt-out-reason", "access-override"]


def test_plain_functions_named_like_the_hook_are_ignored(tmp_path: Path, as_project) -> None:
    as_project(
        fake_app(tmp_path, {"helpers.py": "def filter_queryset_for_user(qs):\n    return qs\n"})
    )
    assert architecture.check_access_override() == []


# --- unpaginated-action ---------------------------------------------------------

ACTIONS = """
class EventViewSet(BaseViewSet):
    model = Event

    @action(detail=False)
    def recent(self, request):
        return Response(EventSerializer(self.get_queryset()[:50], many=True).data)

    @action(detail=False)
    def upcoming(self, request):
        return self.paginated_response(self.get_queryset().filter(upcoming=True))

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        return Response(status=201)
"""


def test_unpaginated_action_detected(tmp_path: Path, as_project) -> None:
    as_project(fake_app(tmp_path, {"viewsets.py": ACTIONS}))
    violations = architecture.check_unpaginated_action()
    assert [v.rule for v in violations] == ["unpaginated-action"]
    assert violations[0].location.endswith("viewsets.py:7")
    assert "paginated_response" in violations[0].hint


def test_unpaginated_action_optout(tmp_path: Path, as_project) -> None:
    content = ACTIONS.replace(
        "    @action(detail=False)\n    def recent",
        "    # karni: allow(unpaginated-action): capped at 50 by the slice, UI needs one call\n"
        "    @action(detail=False)\n    def recent",
    )
    as_project(fake_app(tmp_path, {"viewsets.py": content}))
    assert architecture.check_unpaginated_action() == []


def test_unpaginated_action_optout_needs_a_reason(tmp_path: Path, as_project) -> None:
    content = ACTIONS.replace(
        "many=True).data)",
        "many=True).data)  # karni: allow(unpaginated-action):",
    )
    as_project(fake_app(tmp_path, {"viewsets.py": content}))
    rules = [v.rule for v in architecture.check_unpaginated_action()]
    assert rules == ["opt-out-reason", "unpaginated-action"]


# --- entry points -------------------------------------------------------------


def test_entry_points_registered() -> None:
    from importlib.metadata import entry_points

    names = {ep.name for ep in entry_points(group="karni.checks")}
    assert {"architecture", "duplication"} <= names


def test_run_checks_returns_strings(monkeypatch) -> None:
    monkeypatch.setattr(architecture, "project_app_configs", lambda: [])
    monkeypatch.setattr(_source, "project_app_configs", lambda: [])
    assert architecture.run_checks() == []
