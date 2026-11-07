"""``karni ui detect --css``: any stylesheet onto Karni's tokens, graded found / inferred / defaulted.

The fixtures in tests/fixtures/ui/css/ are six different designs: a bakery
menu with custom properties, a Bootstrap 5 theme with a dark variant, a
clinic site with no variables at all, a dark-only venue theme, a portfolio
read through its pages' <link> tags and @import, and a light theme that
follows the system's dark preference.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.uitheme import colour, detect_css, render
from karni_cli.uitheme.model import Detection, Mapping
from karni_cli.uitheme.plaincss import classify, resolve

CSS = Path(__file__).parent / "fixtures" / "ui" / "css"
UI = Path(__file__).parent / "fixtures" / "ui"


def run(*args: str) -> Result:
    return CliRunner().invoke(app, ["ui", "detect", *args])


def ok(*args: str) -> Result:
    result = run(*args)
    assert result.exit_code == 0, f"{args}: {result.output}\n{result.exception!r}"
    return result


def fails(*args: str, code: str) -> str:
    result = run(*args)
    assert result.exit_code != 0, result.output
    message = str(result.exception) if result.exception else result.output
    assert message.startswith(f"{code}:"), message
    return message


def by_token(entries: list[Any]) -> dict[tuple[str, str], Any]:
    """(token, scheme) -> provenance."""
    return {(entry.token, entry.scheme): entry for entry in entries}


# the function ---------------------------------------------------------------------


def test_custom_properties_are_found_and_resolved_to_literals() -> None:
    found = detect_css(CSS / "bakery" / "menu.css")
    assert found.detection.source == "css"
    assert found.detection.label == "plain CSS (1 stylesheet)"
    tokens = by_token(found.found)
    assert tokens[("--karni-color-primary", "light")].source == "--brand"  # not --brand-600
    assert tokens[("--karni-color-primary", "light")].value == "#8a3b12"
    assert tokens[("--karni-color-background", "light")].source == "--paper"
    assert tokens[("--karni-color-foreground", "light")].source == "--ink"
    assert tokens[("--karni-color-border", "light")].source == "--line"
    assert tokens[("--karni-color-destructive", "light")].value == "#b3261e"
    assert tokens[("--karni-radius", "light")].value == "10px"
    assert tokens[("--karni-font-sans", "light")].source == "--font-body"
    inferred = by_token(found.inferred)
    # The buttons are painted in the brand colour, so their text colour is its foreground.
    assert inferred[("--karni-color-primary-foreground", "light")].source == ".btn { color }"
    assert inferred[("--karni-color-primary-foreground", "light")].value == "white"
    assert inferred[("--karni-color-ring", "light")].value == "#8a3b12"
    assert inferred[("--karni-color-input", "light")].value == "#e6d5c3"
    defaulted = dict(found.defaulted)
    assert set(defaulted) == {
        "--karni-color-muted",
        "--karni-color-muted-foreground",
        "--karni-font-mono",
    }
    unmapped = {u.name: u for u in found.detection.unmapped}
    assert unmapped["--font-display"].suggestion == '--karni-font-sans: "Fraunces", Georgia, serif;'
    assert unmapped["--accent"].suggestion == "--karni-color-accent: #d98c3f;"
    assert any("dark mode keeps Karni's dark palette" in note for note in found.detection.notes)


def test_bootstrap_variables_with_a_dark_variant() -> None:
    found = detect_css(CSS / "bootstrap" / "theme.css")
    assert found.detection.label.startswith("Bootstrap-style CSS variables")
    tokens = by_token(found.found)
    assert tokens[("--karni-color-primary", "light")].source == "--bs-primary"
    assert tokens[("--karni-color-background", "light")].value == "#fff"
    assert tokens[("--karni-color-muted", "light")].source == "--bs-secondary-bg"
    assert tokens[("--karni-color-muted-foreground", "light")].source == "--bs-secondary-color"
    assert tokens[("--karni-color-destructive", "light")].value == "#dc3545"
    assert tokens[("--karni-radius", "light")].value == "0.375rem"
    # var() chains resolve to the literal, and --bs-primary-rgb is a channel variable, skipped.
    assert tokens[("--karni-font-sans", "light")].source == "--bs-body-font-family"
    assert tokens[("--karni-font-sans", "light")].value.startswith("system-ui, -apple-system")
    assert tokens[("--karni-font-mono", "light")].source == "--bs-font-monospace"
    assert tokens[("--karni-color-background", "dark")].value == "#212529"
    assert tokens[("--karni-color-border", "dark")].value == "#495057"
    assert ("--karni-color-primary", "dark") not in tokens  # not redeclared in the dark block
    inferred = by_token(found.inferred)
    assert inferred[("--karni-color-primary-foreground", "light")].value == "#fff"
    assert inferred[("--karni-color-input", "dark")].value == "#495057"
    assert not any(name.endswith("-rgb") for name in (u.name for u in found.detection.unmapped))
    assert dict(found.defaulted) == {}


def test_a_stylesheet_without_variables_is_read_from_its_rules() -> None:
    found = detect_css(CSS / "clinic" / "style.css")
    assert found.found == []
    inferred = by_token(found.inferred)
    assert inferred[("--karni-color-primary", "light")].source == "button { background-color }"
    assert inferred[("--karni-color-primary", "light")].value == "#0e7c86"
    assert inferred[("--karni-color-primary-foreground", "light")].source == "button { color }"
    assert inferred[("--karni-color-background", "light")].value == "#f7fbfc"
    assert inferred[("--karni-color-foreground", "light")].source == "body { color }"
    assert inferred[("--karni-color-border", "light")].source == "input { border }"
    assert inferred[("--karni-color-border", "light")].value == "#cbd5dc"
    assert inferred[("--karni-color-muted-foreground", "light")].source == ".text-muted { color }"
    assert inferred[("--karni-color-destructive", "light")].source == ".error { color }"
    assert inferred[("--karni-radius", "light")].value == "6px"
    # The font comes out of the `font` shorthand.
    assert inferred[("--karni-font-sans", "light")].value == '"Nunito", "Segoe UI", sans-serif'
    assert inferred[("--karni-font-sans", "light")].source == "body { font }"
    assert set(dict(found.defaulted)) == {"--karni-color-muted", "--karni-font-mono"}


def test_a_dark_only_design_is_written_for_both_modes() -> None:
    found = detect_css(CSS / "night" / "theme.css")
    tokens = by_token(found.found)
    assert tokens[("--karni-color-background", "both")].value == "#0f1115"
    assert tokens[("--karni-color-primary", "both")].value == "hsl(45 100% 55%)"
    assert tokens[("--karni-color-primary-foreground", "both")].source == "--color-primary-contrast"
    assert tokens[("--karni-color-border", "both")].value == "rgb(255 255 255 / 0.12)"
    assert tokens[("--karni-color-muted-foreground", "both")].source == "--color-text-muted"
    assert tokens[("--karni-color-destructive", "both")].source == "--color-error"
    # Non-colour tokens apply in both modes from :root.
    assert tokens[("--karni-radius", "light")].value == "2px"
    assert tokens[("--karni-font-mono", "light")].value == '"IBM Plex Mono", monospace'
    assert any("written for both of Karni's modes" in note for note in found.detection.notes)
    theme = found.theme_css("2026-01-01")
    assert ":root,\n.dark {\n" in theme and ":root:not(.dark)" not in theme
    assert "\n:root {\n  --karni-radius: 2px;" in theme


def test_a_directory_is_read_through_its_pages_in_link_order() -> None:
    found = detect_css(CSS / "portfolio")
    assert found.detection.label == "plain CSS (4 stylesheets)"
    names = [Path(file).name for file in found.detection.files]
    # normalize first (linked first), then tokens.css (@import of site.css), site.css, about.css.
    assert names == ["normalize.css", "tokens.css", "site.css", "about.css"]
    assert "unused.css" not in names  # no page links it
    tokens = by_token(found.found)
    assert tokens[("--karni-color-background", "light")].value == "#fcfcfa"  # site, not the reset
    assert tokens[("--karni-color-primary", "light")].source == "--accent"
    assert "no primary or brand variable" in tokens[("--karni-color-primary", "light")].note
    assert tokens[("--karni-font-sans", "light")].value == '"Lora", Georgia, serif'
    assert tokens[("--karni-radius", "light")].value == "0"
    assert any("remote stylesheet is not read" in note for note in found.detection.notes)


def test_a_prefers_color_scheme_block_is_the_dark_variant() -> None:
    found = detect_css(CSS / "switching" / "app.css")
    tokens = by_token(found.found)
    assert tokens[("--karni-color-background", "light")].value == "#ffffff"
    assert tokens[("--karni-color-background", "dark")].value == "#12121a"
    assert tokens[("--karni-color-muted-foreground", "dark")].value == "#a0a2bc"
    assert tokens[("--karni-color-primary", "light")].value == "oklch(0.55 0.2 250)"
    # oklch is copied as written, but no text colour is derived from it.
    assert ("--karni-color-primary-foreground", "light") not in by_token(found.inferred)
    assert "--karni-color-primary-foreground" in dict(found.defaulted)
    assert any("does not compute" in note for note in found.detection.notes)
    theme = found.theme_css("2026-01-01")
    assert (
        ":root:not(.dark) {\n" in theme
        and "\n.dark {\n  --karni-color-background: #12121a;" in theme
    )


def test_several_paths_cascade_in_order(tmp_path: Path) -> None:
    first = tmp_path / "a.css"
    second = tmp_path / "b.css"
    first.write_text(":root { --brand: #111111; --radius: 4px; }\n")
    second.write_text(":root { --brand: #222222; }\n")
    found = detect_css([first, second])
    tokens = by_token(found.found)
    assert tokens[("--karni-color-primary", "light")].value == "#222222"
    assert tokens[("--karni-radius", "light")].value == "4px"
    assert found.detection.label == "plain CSS (2 stylesheets)"


def test_an_unresolvable_variable_is_reported_not_guessed(tmp_path: Path) -> None:
    sheet = tmp_path / "x.css"
    sheet.write_text(":root { --brand: var(--undefined); --bg: var(--missing, #fafafa); }\n")
    found = detect_css(sheet)
    unmapped = {u.name: u.reason for u in found.detection.unmapped}
    assert "do not define" in unmapped["--brand"]
    assert by_token(found.found)[("--karni-color-background", "light")].value == "#fafafa"


def test_a_value_that_is_not_the_role_kind_is_reported(tmp_path: Path) -> None:
    sheet = tmp_path / "x.css"
    sheet.write_text(":root { --primary: 222 47% 11%; --radius: bold; --font-sans: #fff; }\n")
    found = detect_css(sheet)
    unmapped = {u.name: u.reason for u in found.detection.unmapped}
    assert "is not a colour" in unmapped["--primary"]
    assert "is not a length" in unmapped["--radius"]
    assert "is not a font family" in unmapped["--font-sans"]
    assert found.found == []


def test_a_missing_path_or_an_empty_directory_is_c303(tmp_path: Path) -> None:
    with pytest.raises(CliError) as caught:
        detect_css(tmp_path / "nope.css")
    assert caught.value.code == "C303" and "no such file" in caught.value.message
    (tmp_path / "empty").mkdir()
    with pytest.raises(CliError) as caught:
        detect_css(tmp_path / "empty")
    assert caught.value.code == "C303" and "no stylesheet found" in caught.value.message
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(CliError) as caught:
        detect_css(tmp_path / "notes.txt")
    assert caught.value.code == "C303" and "not a stylesheet" in caught.value.message


def test_the_json_shape() -> None:
    data = detect_css(CSS / "bakery" / "menu.css").as_dict()
    assert set(data) == {
        "source",
        "detected",
        "files_read",
        "mapped",
        "found",
        "inferred",
        "defaulted",
        "not_mapped",
        "notes",
    }
    assert data["source"] == "css"
    assert {m["to"] for m in data["mapped"]} == {
        entry["token"] for entry in data["found"] + data["inferred"]
    }
    assert data["found"][0] == {
        "token": "--karni-color-primary",
        "scheme": "light",
        "from": "--brand",
        "value": "#8a3b12",
    }
    assert {"token": "--karni-font-mono", "reason": "no monospace font variable"} in data[
        "defaulted"
    ]
    json.dumps(data)  # serialisable


# the names and the colours ----------------------------------------------------------


@pytest.mark.parametrize(
    ("variable", "role", "rank"),
    [
        ("--brand", "primary", 0),
        ("--brand-600", "primary", 2),
        ("--primary-500", "primary", 3),
        ("--color-primary-main", "primary", 1),
        ("--bs-body-bg", "background", 0),
        ("--wp--preset--color--background", "background", 0),
        ("--md-sys-color-on-surface", "foreground", 0),
        ("--text-muted", "muted-foreground", 0),
        ("--bs-secondary-color", "muted-foreground", 0),
        ("--border-radius", "radius", 0),
        ("--pico-font-family", "font-sans", 0),
        ("--font-heading", "font-heading", 0),
    ],
)
def test_variable_names_that_mean_a_role(variable: str, role: str, rank: int) -> None:
    classified = classify(variable)
    assert classified is not None and (classified[0], classified[2]) == (role, rank)


@pytest.mark.parametrize(
    "variable", ["--bs-primary-rgb", "--brand-300", "--sidebar", "--bs-secondary"]
)
def test_variable_names_that_mean_nothing_karni_reads(variable: str) -> None:
    assert classify(variable) is None


def test_var_chains_resolve_through_the_stylesheet() -> None:
    variables = {"--a": "var(--b)", "--b": "rgb(var(--c-rgb))", "--c-rgb": "1, 2, 3"}
    assert resolve("var(--a)", variables) == "rgb(1, 2, 3)"
    assert resolve("var(--zzz, 4px)", variables) == "4px"
    assert resolve("var(--zzz)", variables) is None
    variables["--loop"] = "var(--loop)"
    assert resolve("var(--loop)", variables) is None


def test_colour_arithmetic() -> None:
    assert colour.parse("#fff") == colour.Rgba(255, 255, 255, 1.0)
    translucent = colour.parse("#00000080")
    assert translucent is not None and round(translucent.a, 2) == 0.5
    assert colour.parse("rgb(13, 110, 253)") == colour.Rgba(13, 110, 253, 1.0)
    assert colour.parse("rgb(13 110 253 / 50%)") == colour.Rgba(13, 110, 253, 0.5)
    white = colour.parse("hsl(0 0% 100%)")
    assert white is not None and (round(white.r), round(white.g), round(white.b)) == (255, 255, 255)
    assert colour.parse("oklch(0.5 0.1 200)") is None
    assert colour.parse("transparent") is not None
    black, white = colour.Rgba(0, 0, 0), colour.Rgba(255, 255, 255)
    assert round(colour.contrast(black, white), 1) == 21.0
    assert colour.is_dark(colour.Rgba(15, 17, 21)) and not colour.is_dark(white)
    assert colour.readable_on(colour.Rgba(13, 110, 253), ["#212529", "#ffffff"]) == "#ffffff"
    assert (
        colour.readable_on(colour.Rgba(13, 110, 253), ["#222222"]) == "white"
    )  # too little contrast
    assert colour.readable_on(colour.Rgba(250, 250, 250), []) == "black"


# the generated file ----------------------------------------------------------------


def test_light_colours_never_override_karnis_dark_palette() -> None:
    """karni-theme.css loads after styles.css: a :root colour would tie with .dark and win."""
    detection = Detection("css", "test")
    detection.mappings = [
        Mapping("--brand", "--karni-color-primary", "#123456", "light"),
        Mapping("--radius", "--karni-radius", "3px", "light"),
        Mapping("--font", "--karni-font-sans", "Inter", "light"),
        Mapping("--dark-brand", "--karni-color-primary", "#abcdef", "dark"),
        Mapping("--line", "--karni-color-border", "var(--line)", "both"),
    ]
    theme = render.theme_body(detection)
    assert ":root:not(.dark) {\n  --karni-color-primary: #123456; /* --brand */\n}" in theme
    assert (
        ":root {\n  --karni-radius: 3px; /* --radius */\n  --karni-font-sans: Inter; /* --font */\n}"
        in theme
    )
    assert ".dark {\n  --karni-color-primary: #abcdef; /* --dark-brand */\n}" in theme
    assert ":root,\n.dark {\n  --karni-color-border: var(--line);\n}" in theme
    assert theme.index(":root,\n.dark") < theme.index(":root:not(.dark)") < theme.index("\n:root {")


# the command -------------------------------------------------------------------------


def frontend(tmp_path: Path) -> Path:
    target = tmp_path / "plain"
    shutil.copytree(UI / "plain", target)
    return target


def test_the_command_writes_and_wires_the_theme_into_the_frontend(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    result = ok("--frontend", str(root), "--css", str(CSS / "clinic" / "style.css"))
    assert "Found (0):" in result.output and "Inferred (11):" in result.output
    assert "Defaulted (2): Karni's own value applies" in result.output
    assert "button { background-color }" in result.output
    theme = root / "src" / "karni-theme.css"
    assert theme.is_file() and render.state(theme) == "unmodified"
    text = theme.read_text()
    assert "Detected: plain CSS (1 stylesheet)" in text
    assert ":root:not(.dark) {\n" in text and "--karni-color-primary: #0e7c86;" in text
    assert "--karni-radius: 6px;" in text
    main = (root / "src" / "main.tsx").read_text()
    assert 'import "@karni/ui/styles.css";\nimport "./karni-theme.css";' in main
    # A second run finds the same file and changes nothing.
    again = ok("--frontend", str(root), "--css", str(CSS / "clinic" / "style.css"))
    assert "unchanged: src/karni-theme.css" in again.output


def test_the_command_keeps_an_edited_theme_unless_forced(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    ok("--frontend", str(root), "--css", str(CSS / "bakery" / "menu.css"))
    theme = root / "src" / "karni-theme.css"
    theme.write_text(theme.read_text() + "\n:root { --karni-radius: 0; }\n")
    message = fails("--frontend", str(root), "--css", str(CSS / "bakery" / "menu.css"), code="C302")
    assert "--force" in message
    ok("--frontend", str(root), "--css", str(CSS / "bakery" / "menu.css"), "--force")
    assert "--karni-radius: 10px;" in theme.read_text()


def test_the_command_takes_several_stylesheets_and_a_directory(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    result = ok(
        "--frontend",
        str(root),
        "--css",
        str(CSS / "clinic" / "style.css"),
        "--css",
        str(CSS / "portfolio"),
        "--json",
    )
    data = json.loads(result.output)
    assert data["source"] == "css" and data["detected"] == "plain CSS (5 stylesheets)"
    assert [Path(f).name for f in data["files_read"]] == [
        "style.css",
        "normalize.css",
        "tokens.css",
        "site.css",
        "about.css",
    ]
    assert {"found", "inferred", "defaulted", "not_mapped", "notes", "files", "wiring"} <= set(data)
    primary = next(m for m in data["mapped"] if m["to"] == "--karni-color-primary")
    assert primary["value"] == "#2f5d50"  # the portfolio's, read last
    assert data["files"] == [
        {"path": "src/karni-theme.css", "action": "written", "state": "absent"}
    ]


def test_the_json_report_prints_the_dry_run_file(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    result = ok(
        "--frontend", str(root), "--css", str(CSS / "night" / "theme.css"), "--dry-run", "--json"
    )
    data = json.loads(result.output)
    assert data["dry_run"] is True and data["files"][0]["action"] == "would write"
    assert ":root,\n.dark {" in data["files"][0]["content"]
    assert not (root / "src" / "karni-theme.css").exists()


def test_without_a_frontend_the_report_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = ok("--css", str(CSS / "clinic" / "style.css"), "--dry-run")
    assert "would write: karni-theme.css" in result.output
    assert "no frontend was found here" in result.output
    # --output writes the file there, unwired.
    out = tmp_path / "static" / "css" / "karni-theme.css"
    result = ok("--css", str(CSS / "clinic" / "style.css"), "--output", str(out))
    assert out.is_file() and "--karni-color-primary: #0e7c86;" in out.read_text()
    assert "written: static/css/karni-theme.css" in result.output
    # --json without anywhere to write is a report only.
    data = json.loads(ok("--css", str(CSS / "clinic" / "style.css"), "--json").output)
    assert data["dry_run"] is True
    # Without --output or --dry-run there is nothing to do: C301 says what to pass.
    message = fails("--css", str(CSS / "clinic" / "style.css"), code="C301")
    assert "--output" in message and "--dry-run" in message


def test_css_and_source_together_is_c106(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    message = fails(
        "--frontend",
        str(root),
        "--css",
        str(CSS / "clinic" / "style.css"),
        "--source",
        "mui",
        code="C106",
    )
    assert "--source" in message


def test_a_missing_css_path_is_c303_from_the_command(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    message = fails("--frontend", str(root), "--css", str(tmp_path / "missing.css"), code="C303")
    assert "no such file" in message
