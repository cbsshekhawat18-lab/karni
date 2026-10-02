"""karni.rules.py: static parsing, validation and resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from karni.agent import dump
from karni.agent.overrides import (
    OverrideError,
    parse_overrides,
    read_overrides,
    resolve_rules,
)

VALID = '''"""Project rules."""
ADD = [
    {"code": "P001", "rule": "Money is always a Decimal, never a float.",
     "summary": "Money is Decimal.", "category": "billing", "severity": "must"},
]
ADD += [{"code": "P002", "rule": "Invoices are immutable once sent."}]
OVERRIDE = {"K007": {"summary": "Commands: just up."}}
DISABLE = ["K304"]
DISABLE += ["K307"]
ADAPTERS = {"disable": ["copilot"], "paths": {"windsurf": ".devin/rules/karni.md"}}
'''


def _parse(source: str) -> object:
    return parse_overrides(source, Path("karni.rules.py"))


def test_valid_file_resolves(tmp_path: Path) -> None:
    (tmp_path / "karni.rules.py").write_text(VALID)
    overrides = read_overrides(tmp_path)
    rules = resolve_rules(overrides)
    codes = [r.code for r in rules]
    assert "K304" not in codes and "K307" not in codes
    assert codes[-2:] == ["P001", "P002"]  # project categories render after Karni's
    by_code = {r.code: r for r in rules}
    assert by_code["K007"].summary == "Commands: just up."
    assert by_code["K007"].rule.startswith("Use the project commands")  # untouched fields
    assert by_code["P002"].summary == "Invoices are immutable once sent."
    assert by_code["P002"].category == "project"
    assert by_code["P001"].category == "billing"
    assert overrides.adapters["paths"] == {"windsurf": ".devin/rules/karni.md"}

    data = dump(tmp_path)
    assert data["categories"][-2:] == ["billing", "project"]
    assert data["overrides_file"].endswith("karni.rules.py")


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_overrides(tmp_path).add == []
    assert read_overrides(None).path is None


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("import os\n", "only literal assignments"),
        ("ADD = [dict(code='P001')]\n", "must be a literal"),
        ("FOO = 1\n", "only literal assignments"),
        ("ADD = [{'code': 'K999', 'rule': 'x'}]\n", "must look like P001"),
        ("ADD = [{'code': 'P001'}]\n", "non-empty 'rule'"),
        ("ADD = [{'code': 'P001', 'rule': 'a'}, {'code': 'P001', 'rule': 'b'}]\n", "twice"),
        ("ADD = [{'code': 'P001', 'rule': 'a', 'color': 'red'}]\n", "unknown field"),
        ("ADD = [{'code': 'P001', 'rule': 'a', 'severity': 'loud'}]\n", "severity"),
        ("OVERRIDE = {'K999': {'summary': 'x'}}\n", "not a Karni rule code"),
        ("OVERRIDE = {'K001': {'code': 'K002'}}\n", "unknown field"),
        ("DISABLE = ['K998']\n", "not a Karni rule code"),
        ("ADAPTERS = {'rename': {}}\n", "ADAPTERS accepts only"),
        ("ADD += {'code': 'P001'}\n", "expects a list"),
        ("ADD = [\n", "syntax error"),
    ],
)
def test_malformed_files_name_the_problem(source: str, message: str) -> None:
    with pytest.raises(OverrideError, match=message):
        _parse(source)


def test_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    (tmp_path / "karni.rules.py").write_text(f"open({str(marker)!r}, 'w')\n")
    with pytest.raises(OverrideError):
        read_overrides(tmp_path)
    assert not marker.exists()
