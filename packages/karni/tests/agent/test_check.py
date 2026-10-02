"""``karni rules --check`` static checks against known-bad and known-good fixtures."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from karni.agent import check_paths
from karni.agent.check import check_file, check_source, scoped_path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BAD_PY = FIXTURES / "app" / "bad_models.py"
BAD_PAGE = FIXTURES / "frontend" / "src" / "pages" / "bad_page.tsx"


@pytest.fixture(autouse=True)
def _in_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    # Allowances match relative to the root/cwd, as in a project; the
    # repository's own tests/ directory above must not count as `*/tests/*`.
    monkeypatch.chdir(FIXTURES)


def _expected(path: Path) -> list[tuple[int, str]]:
    """``# K###`` / ``(K###...)`` markers written next to each bad line."""
    found = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        for code in re.findall(r"#\s*(K\d{3})\s*$", line):
            found.append((number, code))
    return found


def test_bad_python_reports_every_marked_line() -> None:
    findings = check_file(BAD_PY)
    got = {(f.line, f.code) for f in findings}
    assert set(_expected(BAD_PY)) <= got
    # the reason-less opt-out on the last line is K005 and does NOT suppress
    assert any(f.code == "K005" for f in findings)
    for finding in findings:
        assert finding.fix and finding.message


def test_bad_page_reports_each_frontend_rule() -> None:
    codes = {(f.code, f.rule_id) for f in check_file(BAD_PAGE)}
    assert {
        ("K201", "karni/no-raw-elements"),
        ("K202", "karni/max-page-lines"),
        ("K203", "karni/no-deep-imports"),
        ("K204", "karni/no-direct-http"),
        ("K005", "eslint-comments/require-description"),
    } <= codes


@pytest.mark.parametrize(
    "rel",
    [
        "app/good_models.py",
        "app/sql/report.py",
        "frontend/src/pages/good_page.tsx",
    ],
)
def test_good_fixtures_are_clean(rel: str) -> None:
    assert check_file(FIXTURES / rel) == []


def test_opt_outs_with_reasons_suppress() -> None:
    source = (
        "from django.db import models\n"
        "# karni: allow(model-base): legacy table, migrated in Q3\n"
        "class Legacy(models.Model):\n"
        "    pass\n"
        "import requests  # karni: allow(http-client): vendored SDK shim\n"
    )
    assert check_source("./app/models.py", source) == []
    tsx = (
        "// eslint-disable-next-line karni/no-direct-http -- health probe before the client\n"
        'void fetch("/health/");\n'
    )
    assert check_source("./src/pages/x.tsx", tsx) == []


def test_path_allowances() -> None:
    raw = "def f(c):\n    c.execute('SELECT 1')\n"
    assert check_source("./billing/sql/q.py", raw) == []
    assert [f.code for f in check_source("./billing/q.py", raw)] == ["K104"]
    http = "import httpx\n"
    assert check_source("./billing/services/pay.py", http) == []
    assert [f.code for f in check_source("./billing/views.py", http)] == ["K105"]
    fetch = 'export const get = () => fetch("/api/x/");\n'
    assert check_source("./frontend/src/api/client.ts", fetch) == []
    assert check_source("./frontend/src/thing.test.ts", fetch) == []
    assert [f.code for f in check_source("./frontend/src/hooks.ts", fetch)] == ["K204"]


def test_page_cap_counts_physical_lines() -> None:
    fifty = "\n".join(["// line"] * 50) + "\n"
    assert check_source("./src/pages/p.tsx", fifty) == []
    assert [f.code for f in check_source("./src/pages/p.tsx", fifty + "// 51\n")] == ["K202"]
    assert check_source("./src/components/p.tsx", fifty + "// 51\n") == []


def test_access_rules() -> None:
    missing = (
        "from karni.api import BaseViewSet\n"
        "class A(BaseViewSet):\n    model = X\n"
        "class Base(BaseViewSet):\n    pass\n"  # abstract: no model
        "class B(A):\n    model = X\n"  # inherits A's (unknown) access
        "class C(BaseViewSet):\n    model = X\n    def get_access(self):\n        return None\n"
    )
    assert [(f.code, f.line) for f in check_source("./app/viewsets.py", missing)] == [("K109", 2)]
    override = (
        "class V(Base):\n"
        "    @property\n"
        "    def x(self):\n        return 1\n"
        "    def filter_queryset_for_user(self, qs):\n        return qs\n"
        "class W(Base):\n"
        "    # karni: allow(access-override): rows come from the billing service\n"
        "    def filter_queryset_for_user(self, qs):\n        return qs\n"
        "def filter_queryset_for_user(qs):\n    return qs\n"
    )
    assert [(f.code, f.line) for f in check_source("./app/viewsets.py", override)] == [("K110", 5)]


def test_mixins_and_abstract_models_pass() -> None:
    source = (
        "from django.db import models\n"
        "from karni.models import AuditedModel, UUIDModel\n"
        "class A(UUIDModel, AuditedModel):\n    pass\n"
        "class B(models.Model):\n    class Meta:\n        abstract = True\n"
    )
    assert check_source("./app/models.py", source) == []


def test_scoped_path_is_root_relative(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "app" / "views.py"
    target.parent.mkdir(parents=True)
    target.write_text("import requests\n")
    assert scoped_path(target, tmp_path / "tests") == "./app/views.py"
    found = check_paths([target], tmp_path / "tests")
    assert [f["code"] for f in found] == ["K105"]


def test_disable_filters_check_paths(tmp_path: Path) -> None:
    (tmp_path / "karni.rules.py").write_text('DISABLE = ["K105"]\n')
    target = tmp_path / "views.py"
    target.write_text("import requests\n")
    assert check_paths([target], tmp_path) == []


def test_unsupported_and_unparsable() -> None:
    assert check_source("./notes.md", "<table>") == []
    with pytest.raises(ValueError, match="cannot parse"):
        check_source("./x.py", "def (:\n")


def test_module_bridge_prints_json() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "karni.agent", "check", "--root", ".", "app/bad_models.py"],
        cwd=FIXTURES,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    findings = json.loads(proc.stdout)
    assert {f["code"] for f in findings} >= {
        "K101",
        "K102",
        "K103",
        "K104",
        "K105",
        "K106",
        "K109",
        "K110",
    }
    assert all(f["path"] == "app/bad_models.py" for f in findings)

    dumped = subprocess.run(
        [sys.executable, "-m", "karni.agent", "dump"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(dumped.stdout)["rules"]


def test_module_bridge_rejects_bad_overrides(tmp_path: Path) -> None:
    (tmp_path / "karni.rules.py").write_text("import os\n")
    proc = subprocess.run(
        [sys.executable, "-m", "karni.agent", "dump", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "only literal assignments" in proc.stderr
