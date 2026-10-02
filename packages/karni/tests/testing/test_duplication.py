"""Tests for the AST duplicate detector."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from karni.testing import _source, duplication

BODY = """
def {name}(order):
    total = 0
    items = list(order.items.all())
    for item in items:
        total += item.price * item.quantity
    if total > 100:
        total = total * 0.9
    order.total = total
    order.save()
    return total
"""


@pytest.fixture
def as_project(monkeypatch):
    def _install(tmp_path: Path, files: dict[str, str]):
        for name, content in files.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        cfg = SimpleNamespace(path=str(tmp_path), name="fakeapp", label="fakeapp")
        monkeypatch.setattr(duplication, "project_app_configs", lambda: [cfg])
        monkeypatch.setattr(_source, "project_app_configs", lambda: [cfg])
        _source._file_lines.cache_clear()

    return _install


def test_clone_pair_detected(tmp_path, as_project) -> None:
    as_project(
        tmp_path,
        {"a.py": BODY.format(name="calc_a"), "b.py": BODY.format(name="calc_b")},
    )
    failures = duplication.run_check()
    assert len(failures) == 2  # one report per clone member
    assert all("[duplicate]" in f for f in failures)
    assert any("a.py" in f and "b.py" in f for f in failures)


def test_below_threshold_ignored(tmp_path, as_project, settings) -> None:
    settings.KARNI_ARCHITECTURE = {"dup": {"min_statements": 30, "exclude": []}}
    as_project(
        tmp_path,
        {"a.py": BODY.format(name="calc_a"), "b.py": BODY.format(name="calc_b")},
    )
    assert duplication.run_check() == []


def test_migrations_excluded_by_default(tmp_path, as_project) -> None:
    as_project(
        tmp_path,
        {
            "migrations/0001_a.py": BODY.format(name="calc_a"),
            "migrations/0002_b.py": BODY.format(name="calc_b"),
        },
    )
    assert duplication.run_check() == []


def test_optout_suppresses_pair_member(tmp_path, as_project) -> None:
    allowed = BODY.format(name="calc_a").replace(
        "def calc_a(order):",
        "# karni: allow(duplicate): intentional fork pending extraction\ndef calc_a(order):",
    )
    as_project(tmp_path, {"a.py": allowed, "b.py": BODY.format(name="calc_b")})
    failures = duplication.run_check()
    assert len(failures) == 1 and "b.py" in failures[0]


def test_unique_functions_clean(tmp_path, as_project) -> None:
    other = """
def different(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c / 4
    e = d ** 2
    f = e % 5
    g = [f for _ in range(3)]
    return sorted(g)
"""
    as_project(tmp_path, {"a.py": BODY.format(name="calc_a"), "b.py": other})
    assert duplication.run_check() == []
