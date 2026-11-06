"""CLI error codes: every CliError is coded, karni explain answers, docs/errors.md is fresh."""

from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import errorcodes
from karni_cli.errordoc import _entry, render
from karni_cli.main import app
from karni_cli.project import CliError

from .conftest import REPO_ROOT, require_modules

PACKAGE = Path(errorcodes.__file__).resolve().parent
runner = CliRunner()


def test_docs_errors_md_is_fresh() -> None:
    require_modules()  # the page lists every module's codes
    docs = (REPO_ROOT / "docs" / "errors.md").read_text(encoding="utf-8")
    assert docs == render(), (
        "docs/errors.md is stale. Regenerate it: python -m karni_cli.errordoc > docs/errors.md"
    )


class _Anchors(HTMLParser):
    """Collects ``id`` attributes the way mkdocs scans a page for anchors."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.ids.update(value for key, value in attrs if key == "id" and value)


def test_every_anchor_on_the_page_is_visible_to_an_html_parser() -> None:
    """A raw ``<title>`` or ``<textarea>`` hid every anchor after it from mkdocs (A6-01)."""
    page = render()
    parser = _Anchors()
    parser.feed(page)
    parser.close()
    assert set(re.findall(r'<a id="([^"]+)"></a>', page)) == parser.ids


def test_registry_text_reaches_the_page_without_raw_tags() -> None:
    entry = {
        "code": "X001",
        "title": "A page's <title> is missing",
        "kind": "check",
        "source": "app/<name>.py",
        "why": "Raw `<textarea>` and <script> in <app>/views.py (inside <!-- a comment -->).",
        "fix": "Use `a < b`, ``x`y``, `plain` and [the docs](errors.md#x001).",
    }
    text = _entry(entry)
    tags = re.findall(r"<(?!a id=|/a>|code>|/code>)[^ >]*", text)
    assert tags == [], tags
    assert "A page's &lt;title> is missing" in text
    assert "from <code>app/&lt;name&gt;.py</code>" in text
    assert "Raw <code>&lt;textarea&gt;</code> and &lt;script> in &lt;app>/views.py" in text
    assert "<code>a &lt; b</code>, ``x`y``, `plain` and [the docs](errors.md#x001)." in text


def test_escaped_text_renders_as_the_registry_wrote_it() -> None:
    markdown = pytest.importorskip("markdown")
    entry = {
        "code": "X001",
        "title": "t",
        "kind": "check",
        "source": "s",
        "why": "show a page's <title> in `<app>/views.py`.",
        "fix": "f",
    }
    html = markdown.markdown(_entry(entry))
    assert "show a page's &lt;title&gt; in <code>&lt;app&gt;/views.py</code>." in html


def test_the_page_documents_every_kind_of_code() -> None:
    page = render()
    for anchor in ("e104", "w101", "c101", "k106", "karni-no-raw-elements"):
        assert f'<a id="{anchor}"></a>' in page, anchor


def test_the_page_documents_module_codes() -> None:
    require_modules("karni-payments")
    assert '<a id="pay004"></a>' in render()


def test_cli_codes_are_unique_and_complete() -> None:
    codes = [code.code for code in errorcodes.CODES]
    assert len(codes) == len(set(codes))
    for code in errorcodes.CODES:
        assert re.match(r"^C\d{3}$", code.code), code.code
        assert code.title and code.why and code.fix and code.source, code.code


def _calls() -> list[tuple[str, int, str | None]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        folders = path.relative_to(PACKAGE).parts[:-1]
        if any(part.startswith("_") for part in folders):
            continue  # bundled copies (_templates, _agent, _changelog, _errorcodes), at any depth
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(getattr(node, "func", None), "id", "")
            # karni build's Stop("C27x", ...) is its CliError: the code comes first
            if isinstance(node, ast.Call) and name in ("CliError", "Stop"):
                code = next((kw.value for kw in node.keywords if kw.arg == "code"), None)
                if name == "Stop" and node.args:
                    code = node.args[0]
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
    from karni_cli.spec.validate import iter_codes

    # karni spec validate reports its codes as issues, not CliErrors (tests/test_spec.py
    # produces each one).
    used = {code for _, _, code in _calls()} | set(iter_codes())
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
    if code.startswith("PAY"):
        require_modules("karni-payments")
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


# settings: karni explain KARNI_SITE_HIGHLIGHT


def test_explain_a_modules_setting() -> None:
    require_modules("karni-site")
    result = runner.invoke(app, ["explain", "KARNI_SITE_HIGHLIGHT"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith("KARNI_SITE_HIGHLIGHT  (a setting of karni-site)")
    assert 'Default:  {"marker": "==", "tag": "mark", "class": ""}' in out
    assert "Set it:   in config/settings.py (no environment variable reads it)" in out
    assert "What:     What a client types around words to highlight them" in out
    assert "Docs:     " in out and out.rstrip().endswith("/settings/#karni_site_highlight")


def test_explain_a_core_setting_and_its_variable() -> None:
    result = runner.invoke(app, ["explain", "karni_phone_country_code", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "KARNI_PHONE_COUNTRY_CODE" and data["env"] == "KARNI_PHONE_COUNTRY_CODE"
    assert data["module"] == "" and data["default"] == "None"
    assert '"44"' in data["description"]
    assert data["url"].endswith("/settings/#karni_phone_country_code")


def test_explain_an_unknown_setting_names_the_fix() -> None:
    result = runner.invoke(app, ["explain", "KARNI_NO_SUCH_THING"])
    assert result.exit_code != 0
    assert isinstance(result.exception, CliError) and result.exception.code == "C373"
    assert "docs/settings.md" in str(result.exception)


def test_the_settings_reference_loads_from_the_wheels_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside a checkout: the bundled reference.py and base.py, modules by their entry points."""
    import shutil
    import sys

    from karni_cli import settingref

    require_modules("karni-site")
    bundled = tmp_path / "karni_cli" / "_settings"
    bundled.mkdir(parents=True)
    conf = REPO_ROOT / "packages" / "karni" / "karni" / "conf"
    for name in ("reference.py", "base.py"):
        shutil.copy2(conf / name, bundled / name)
    monkeypatch.setattr(settingref, "_reference_file", lambda: bundled / "reference.py")
    monkeypatch.delitem(sys.modules, settingref._MODULE_NAME, raising=False)
    try:
        module = settingref.reference_module()
        assert module is not None and Path(str(module.__file__)).parent == bundled
        assert dict(module.module_conf_files())["karni-site"].name == "conf.py"
        core, site = settingref.lookup("KARNI_AUTH_MODE"), settingref.lookup("KARNI_SITE_SEO_QUIET")
        assert core is not None and core["env"] == "KARNI_AUTH_MODE"
        assert site is not None and site["module"] == "karni-site"
    finally:
        sys.modules.pop(settingref._MODULE_NAME, None)
