"""One brand, one source: the admin, the welcome page and the emails read @karni/ui's tokens.

``karni/tokens.css`` (karni.admin's static files) is a byte-for-byte copy of
``packages/karni-ui/src/styles.css``. Everything Django renders takes its
colours from that copy: through ``var(--karni-*)`` where CSS custom
properties work, and as the same values where they cannot (unfold's neutral
scale, inline email styles). These tests fail when any of them drifts.
"""

from __future__ import annotations

import colorsys
import os
import re
from pathlib import Path
from typing import Any

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils.module_loading import import_string

import karni
from karni import links
from karni.admin.theme import ADMIN_PAGES_CSS, TOKENS_CSS, UNFOLD_THEME_CSS, tokens_css
from karni.conf import karni_settings

PACKAGE = Path(karni.__file__).parent
REPO = links.repo_root() or PACKAGE.parents[2]
KARNI_UI_STYLES = REPO / "packages" / "karni-ui" / "src" / "styles.css"
STATIC = PACKAGE / "admin" / "static"

# Karni's own admin templates and their inline <style> blocks.
ADMIN_TEMPLATES = [
    PACKAGE / "admin" / "templates" / "karni_admin" / "import.html",
    PACKAGE / "admin" / "templates" / "karni_admin" / "hard_delete_selected_confirmation.html",
    PACKAGE / "accounts" / "templates" / "karni_accounts" / "permission_matrix.html",
    PACKAGE / "accounts" / "templates" / "karni_accounts" / "permission_matrix_confirm.html",
    PACKAGE / "accounts" / "templates" / "karni_accounts" / "effective_permissions.html",
]
EMAIL_TEMPLATES = sorted((PACKAGE / "accounts" / "templates").rglob("email/*.html"))

# A colour written out instead of read from a token.
COLOUR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(\s*[\d.]"
    r"|:\s*(?:white|black)\b"
)


def _settings() -> dict[str, Any]:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev")
    return namespace


def _triplets(selector: str) -> dict[str, str]:
    """``--karni-<name>: <h s l>`` declarations of the first ``selector {`` block of tokens.css."""
    css = tokens_css()
    block = css[css.index(f"\n{selector} {{") :]
    block = block[: block.index("\n}")]
    return dict(re.findall(r"--karni-([a-z-]+):\s*([\d.]+ [\d.]+% [\d.]+%);", block))


def _hex(triplet: str) -> str:
    hue, saturation, lightness = (float(part.rstrip("%")) for part in triplet.split())
    rgb = colorsys.hls_to_rgb(hue / 360, lightness / 100, saturation / 100)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)


def test_token_stylesheet_is_a_copy_of_karni_ui() -> None:
    if not KARNI_UI_STYLES.exists():
        if os.environ.get("CI"):
            pytest.fail(f"{KARNI_UI_STYLES} is missing: CI must run in the monorepo checkout.")
        pytest.skip("not a monorepo checkout: @karni/ui's source is not next to karni")
    copy = STATIC / TOKENS_CSS
    assert copy.read_bytes() == KARNI_UI_STYLES.read_bytes(), (
        f"{copy.relative_to(REPO)} must be a byte-for-byte copy of @karni/ui's token "
        "stylesheet, the one source of the brand for Django pages. After changing "
        "@karni/ui's tokens, run from the repository root: "
        "cp packages/karni-ui/src/styles.css packages/karni/karni/admin/static/karni/tokens.css"
    )


def test_welcome_page_reads_the_karni_ui_theme_choice() -> None:
    """Same dark-mode rule as @karni/ui's KARNI_THEME_SCRIPT: the stored choice, else the system."""
    from karni.welcome.page import THEME_SCRIPT

    theme_source = REPO / "packages" / "karni-ui" / "src" / "theme" / "theme.tsx"
    if not theme_source.exists():
        pytest.skip("not a monorepo checkout: @karni/ui's source is not next to karni")
    key = re.search(r'THEME_STORAGE_KEY = "([^"]+)"', theme_source.read_text())
    assert key and f"'{key.group(1)}'" in THEME_SCRIPT


@pytest.mark.django_db
def test_theme_stylesheets_are_static_files_and_load_first() -> None:
    for path in (TOKENS_CSS, UNFOLD_THEME_CSS, ADMIN_PAGES_CSS):
        assert finders.find(path), path
    styles = _settings()["UNFOLD"]["STYLES"]
    urls = [import_string(entry)(None) for entry in styles]
    assert urls[0].endswith("/karni/tokens.css")
    assert urls[1].endswith("/karni/unfold-theme.css")


def test_unfold_base_scale_is_the_tokens_gray() -> None:
    """Unfold's static neutral scale holds exactly the values the tokens use."""
    light, dark = _triplets(":root"), _triplets(".dark")
    base = _settings()["UNFOLD"]["COLORS"]["base"]
    expected = {
        "50": dark["foreground"],
        "100": light["muted"],
        "200": light["border"],
        "300": dark["ring"],
        "400": dark["muted-foreground"],
        "500": light["muted-foreground"],
        "800": dark["border"],
        "900": dark["background"],
    }
    for step, triplet in expected.items():
        assert base[step] == f"hsl({triplet})", (
            f'UNFOLD["COLORS"]["base"]["{step}"] in karni/conf/base.py must be '
            f'"hsl({triplet})", the value tokens.css uses there.'
        )
    assert light["foreground"] == dark["background"]  # base-900: light text, dark page
    assert light["secondary"] == light["accent"] == light["muted"]
    assert dark["secondary"] == dark["muted"] == dark["border"]


def test_unfold_primary_and_text_colours_read_the_tokens() -> None:
    colors = _settings()["UNFOLD"]["COLORS"]
    assert colors["primary"]["600"] == "var(--karni-color-primary)"  # buttons, light links
    assert colors["primary"]["500"] == "var(--karni-color-primary)"  # dark-mode links
    assert set(colors["primary"]) == {str(n) for n in (50, *range(100, 1000, 100), 950)}
    for scale in ("primary", "font"):
        for step, value in colors[scale].items():
            assert "var(--" in value and not COLOUR_LITERAL.search(value), (scale, step, value)


@pytest.mark.parametrize(
    "path",
    [STATIC / UNFOLD_THEME_CSS, STATIC / ADMIN_PAGES_CSS, *ADMIN_TEMPLATES],
    ids=lambda path: path.name,
)
def test_admin_styles_write_no_colour(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = "".join(re.findall(r"<style>(.*?)</style>", text, re.S))
    found = COLOUR_LITERAL.findall(text)
    assert not found, f"{path.name} writes colours {found}; use a --karni-color-* token."


def test_karni_admin_pages_include_the_page_styles() -> None:
    for path in ADMIN_TEMPLATES:
        text = path.read_text(encoding="utf-8")
        if "{% block extrastyle %}" not in text:
            continue  # unfold-styled markup only, no stylesheet of its own
        assert '{% include "karni_admin/includes/page_styles.html" %}' in text, path.name


@pytest.mark.django_db
def test_the_admin_loads_the_tokens_before_unfold_theme(admin_client: Any) -> None:
    html = admin_client.get("/admin/").content.decode()
    tokens = html.index("/static/karni/tokens.css")
    assert tokens < html.index("/static/karni/unfold-theme.css")
    assert "--color-primary-600: var(--karni-color-primary)" in html


@pytest.mark.django_db
def test_karni_pages_load_the_tokens_exactly_once(admin_client: Any, settings: Any) -> None:
    """Once from STYLES (a second copy would undo a project's overrides), or from the page."""
    url = reverse("admin:karni_accounts_role_effective_permissions")
    html = admin_client.get(url).content.decode()
    assert html.count("/static/karni/tokens.css") == 1
    assert html.index("/static/karni/tokens.css") < html.index("/static/karni/admin-pages.css")

    settings.UNFOLD = {**settings.UNFOLD, "STYLES": []}  # a project that dropped Karni's theme
    html = admin_client.get(url).content.decode()
    assert html.count("/static/karni/tokens.css") == 1
    assert "/static/karni/unfold-theme.css" not in html


def test_emails_use_the_brand_values() -> None:
    """Inline email CSS cannot read variables: its colours are the light tokens' values."""
    light = _triplets(":root")
    brand = {_hex(light[name]) for name in light}
    assert {"#111827", "#f9fafb", "#6b7280"} <= brand  # primary, its foreground, muted text
    assert EMAIL_TEMPLATES
    for path in EMAIL_TEMPLATES:
        colours = {colour.lower() for colour in re.findall(r"#[0-9a-fA-F]{6}\b", path.read_text())}
        assert colours, path.name
        assert colours <= brand, f"{path.name} uses {sorted(colours - brand)}, not a token value"
