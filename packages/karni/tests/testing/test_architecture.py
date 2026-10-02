"""Tests for karni.testing.architecture — positive, negative and opt-out paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


# --- entry points -------------------------------------------------------------


def test_entry_points_registered() -> None:
    from importlib.metadata import entry_points

    names = {ep.name for ep in entry_points(group="karni.checks")}
    assert {"architecture", "duplication"} <= names


def test_run_checks_returns_strings(monkeypatch) -> None:
    monkeypatch.setattr(architecture, "project_app_configs", lambda: [])
    monkeypatch.setattr(_source, "project_app_configs", lambda: [])
    assert architecture.run_checks() == []
