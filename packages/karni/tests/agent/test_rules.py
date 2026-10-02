"""The rule registry: shape, code scheme, enforcement mapping, import-lightness."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from karni.agent import dump
from karni.agent.rules import (
    CATEGORIES,
    ENFORCEMENT_CODES,
    PROCEDURES,
    RULES,
    SEVERITIES,
    rules_by_code,
)

PACKAGE = Path(__file__).resolve().parents[2]
REPO = PACKAGE.parents[1]
CODE_RANGES = {"workflow": "K0", "backend": "K1", "frontend": "K2", "architecture": "K3"}


def test_codes_are_unique_and_follow_the_scheme() -> None:
    codes = [rule.code for rule in RULES]
    assert len(codes) == len(set(codes))
    for rule in RULES:
        assert re.fullmatch(r"K\d{3}", rule.code), rule.code
        assert rule.category in CATEGORIES
        assert rule.code.startswith(CODE_RANGES[rule.category]), rule.code
        assert rule.severity in SEVERITIES


def test_every_rule_is_complete() -> None:
    for rule in RULES:
        assert rule.summary.strip() and rule.rule.strip() and rule.rationale.strip(), rule.code
        assert len(rule.summary) <= 100, rule.code  # one terse line in `karni rules`


def test_error_severity_iff_enforced() -> None:
    for rule in RULES:
        assert (rule.severity == "error") == bool(rule.enforced_by), rule.code
        if rule.severity == "error":
            assert rule.fix, f"{rule.code}: enforced rules must say how to fix"


def _backend_rule_ids() -> set[str]:
    source = "\n".join(path.read_text() for path in (PACKAGE / "karni" / "testing").glob("*.py"))
    return set(re.findall(r'rule="([a-z-]+)"', source)) | set(
        re.findall(r'"([a-z]+-[a-z-]+)"', source)
    )


def _eslint_rule_ids() -> set[str]:
    rules_dir = REPO / "packages" / "karni-ui" / "eslint-plugin" / "rules"
    return {f"karni/{path.stem}" for path in rules_dir.glob("*.js")}


def test_enforcement_ids_exist_in_the_enforcement_code() -> None:
    backend = _backend_rule_ids()
    eslint = _eslint_rule_ids()
    external = {"jscpd", "eslint-comments/require-description"}
    for rule_id in ENFORCEMENT_CODES:
        if rule_id.startswith("karni/"):
            assert rule_id in eslint, rule_id
        elif rule_id not in external:
            assert rule_id in backend, rule_id


def test_every_backend_and_eslint_rule_has_a_code() -> None:
    documented = {
        "model-base",
        "viewset-base",
        "admin-convention",
        "raw-sql",
        "http-client",
        "redundant-serializer",
        "duplicate",
        "opt-out-reason",
    }
    assert documented <= set(ENFORCEMENT_CODES)
    assert _eslint_rule_ids() <= set(ENFORCEMENT_CODES)


def test_model_layer_is_reflected() -> None:
    k101 = rules_by_code()["K101"]
    for mixin in ("UUIDModel", "TimestampedModel", "SoftDeleteModel", "AuditedModel"):
        assert mixin in k101.rule
    assert "current_user" in rules_by_code()["K108"].rule


def test_procedures_reference_real_codes() -> None:
    codes = set(rules_by_code())
    names = [p.name for p in PROCEDURES]
    assert names == ["new-model", "new-page", "add-module", "new-module"]
    for procedure in PROCEDURES:
        assert "{arguments}" in procedure.intro
        assert set(procedure.rules) <= codes, procedure.name
        assert procedure.steps


def test_dump_is_json_shaped() -> None:
    data = dump()
    assert data["schema"] == 1
    assert [r["code"] for r in data["rules"]][0] == "K001"
    assert data["categories"] == list(CATEGORIES)
    assert data["overrides_file"] is None


@pytest.mark.parametrize("module", ["karni.agent", "karni.agent.rules", "karni.agent.check"])
def test_import_light(module: str) -> None:
    """The CLI reads these without a project: no Django, no settings."""
    code = (
        f"import sys, {module}; "
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('django', 'rest_framework', 'celery')); "
        "assert not bad, bad"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        env={"PATH": "", "PYTHONPATH": str(PACKAGE)},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
