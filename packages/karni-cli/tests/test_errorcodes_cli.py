"""CLI error codes: every CliError is coded, karni explain answers, docs/errors.md is fresh."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import errorcodes
from karni_cli.errordoc import render
from karni_cli.main import app
from karni_cli.project import CliError

from .conftest import REPO_ROOT

PACKAGE = Path(errorcodes.__file__).resolve().parent
runner = CliRunner()


def test_docs_errors_md_is_fresh() -> None:
    docs = (REPO_ROOT / "docs" / "errors.md").read_text(encoding="utf-8")
    assert docs == render(), (
        "docs/errors.md is stale — regenerate it: python -m karni_cli.errordoc > docs/errors.md"
    )


def test_the_page_documents_every_kind_of_code() -> None:
    page = render()
    for anchor in ("e104", "w101", "pay004", "c101", "k106", "karni-no-raw-elements"):
        assert f'<a id="{anchor}"></a>' in page, anchor


def test_cli_codes_are_unique_and_complete() -> None:
    codes = [code.code for code in errorcodes.CODES]
    assert len(codes) == len(set(codes))
    for code in errorcodes.CODES:
        assert re.match(r"^C\d{3}$", code.code), code.code
        assert code.title and code.why and code.fix and code.source, code.code


def _calls() -> list[tuple[str, int, str | None]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if any(part.startswith("_") and part != "__init__.py" for part in path.parts[-2:-1]):
            continue  # bundled copies (_templates, _agent, _changelog, _errorcodes)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "CliError":
                code = next((kw.value for kw in node.keywords if kw.arg == "code"), None)
                literal = (
                    code.value
                    if isinstance(code, ast.Constant) and isinstance(code.value, str)
                    else None
                )
                if code is not None and literal is None:
                    literal = "<dynamic>"
                found.append((path.relative_to(PACKAGE).as_posix(), node.lineno, literal))
    return found


def test_every_cli_error_carries_a_registered_code() -> None:
    calls = _calls()
    assert len(calls) > 100
    missing = [f"{path}:{line}" for path, line, code in calls if code is None]
    assert not missing, f"CliError(..., code=...) is required: {missing}"
    unknown = [
        f"{path}:{line} {code}"
        for path, line, code in calls
        if code not in {None, "<dynamic>"} and errorcodes.lookup(code) is None
    ]
    assert not unknown, f"register these codes in karni_cli/errorcodes.py: {unknown}"


def test_every_cli_code_is_used() -> None:
    used = {code for _, _, code in _calls()}
    unused = [code.code for code in errorcodes.CODES if code.code not in used]
    assert not unused, f"retire or use: {unused}"


def test_a_coded_cli_error_prints_code_message_link() -> None:
    error = CliError("src/app.py already exists — pass --force.", code="C101")
    assert str(error) == (
        f"C101: src/app.py already exists — pass --force. See {errorcodes.docs_url('C101')}"
    )
    assert str(CliError("plain")) == "plain"


@pytest.mark.parametrize(
    ("code", "fragment"),
    [
        ("E104", "Owned('organizer')"),
        ("e104", "Owned('organizer')"),
        ("W101", "APIMeta"),
        ("C101", "--force"),
        ("PAY004", "STRIPE_SECRET_KEY"),
    ],
)
def test_explain_prints_why_and_fix(code: str, fragment: str) -> None:
    result = runner.invoke(app, ["explain", code])
    assert result.exit_code == 0, result.output
    assert result.output.startswith(code.upper())
    assert "Why:" in result.output and "Fix:" in result.output and fragment in result.output
    assert errorcodes.docs_url(code.upper()) in result.output


def test_explain_json() -> None:
    result = runner.invoke(app, ["explain", "E117", "--json"])
    data = json.loads(result.output)
    assert data["code"] == "E117" and data["kind"] == "exception" and data["url"].endswith("#e117")


def test_explain_renders_agent_rules() -> None:
    result = runner.invoke(app, ["explain", "K106"])
    assert result.exit_code == 0 and "K106" in result.output and "Fix:" in result.output


def test_explain_unknown_code_names_the_fix() -> None:
    result = runner.invoke(app, ["explain", "Z999"])
    assert result.exit_code != 0
    assert isinstance(result.exception, CliError) and result.exception.code == "C204"


def test_the_core_registry_loads_without_django() -> None:
    core = errorcodes.core_module()
    assert core is not None and core.__name__ == "karni_cli._bundled_karni_errorcodes"
    assert any(entry.code == "E101" for entry in core.CODES)
