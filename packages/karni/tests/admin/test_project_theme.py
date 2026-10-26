"""One theme for the staff app and the admin: the project's karni-theme.css, served as static."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.urls import reverse
from django.utils.module_loading import import_string

from karni.admin.theme import PROJECT_THEME_CSS, ProjectThemeFinder, project_theme_path
from karni.conf import karni_settings

BRAND = ":root:not(.dark) {\n  --karni-color-primary: #8a3b12;\n}\n"


@pytest.fixture
def theme(tmp_path: Path, settings: Any) -> Path:
    """A project root holding frontend/src/karni-theme.css, as `karni ui detect` writes it."""
    path = tmp_path / "frontend" / "src" / "karni-theme.css"
    path.parent.mkdir(parents=True)
    path.write_text(BRAND, encoding="utf-8")
    settings.BASE_DIR = tmp_path
    return path


def _settings() -> dict[str, Any]:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev")
    return namespace


def test_karni_settings_load_the_project_theme_third() -> None:
    namespace = _settings()
    assert namespace["KARNI_THEME_CSS"] == "frontend/src/karni-theme.css"
    assert "karni.admin.theme.ProjectThemeFinder" in namespace["STATICFILES_FINDERS"]
    styles = namespace["UNFOLD"]["STYLES"]
    assert styles[2] == "karni.admin.theme.project_theme_stylesheet"
    assert import_string(styles[2])(None).endswith("/karni/project-theme.css")


def test_the_default_path_is_read_from_the_project_root(theme: Path) -> None:
    assert project_theme_path() == theme
    assert finders.find(PROJECT_THEME_CSS) == str(theme)
    assert Path(finders.find(PROJECT_THEME_CSS, find_all=True)[0]).read_text() == BRAND


def test_another_file_or_none(theme: Path, settings: Any, tmp_path: Path) -> None:
    other = tmp_path / "brand.css"
    other.write_text(":root { --karni-radius: 0; }\n")
    settings.KARNI_THEME_CSS = str(other)
    assert project_theme_path() == other
    settings.KARNI_THEME_CSS = ""
    assert project_theme_path() is None


def test_without_a_theme_the_url_serves_an_empty_stylesheet(settings: Any, tmp_path: Path) -> None:
    settings.BASE_DIR = tmp_path
    assert project_theme_path() is None
    found = finders.find(PROJECT_THEME_CSS)
    assert found is not None
    text = Path(found).read_text()
    assert "karni ui detect" in text and "--karni-" not in text.replace("--karni-*", "")


def test_the_finder_answers_only_its_own_path() -> None:
    finder = ProjectThemeFinder()
    assert finder.find("karni/tokens.css") == []
    assert finder.find("karni/tokens.css", find_all=True) == []
    # Through Django's lookup, a file nobody has stays missing.
    assert finders.find("nowhere/missing.css") is None


def test_collectstatic_copies_the_project_theme(theme: Path, settings: Any, tmp_path: Path) -> None:
    settings.STATIC_ROOT = str(tmp_path / "collected")
    call_command("collectstatic", interactive=False, verbosity=0)
    assert (tmp_path / "collected" / "karni" / "project-theme.css").read_text() == BRAND


@pytest.mark.django_db
def test_the_admin_loads_it_after_karnis_own_from_the_site_itself(
    admin_client: Any, theme: Path
) -> None:
    response = admin_client.get("/admin/")
    html = response.content.decode()
    assert html.index("/static/karni/unfold-theme.css") < html.index(
        '<link href="/static/karni/project-theme.css"'
    )
    # Same origin: the Content-Security-Policy's style-src 'self' allows it.
    policy = response.headers.get("Content-Security-Policy") or response.headers.get(
        "Content-Security-Policy-Report-Only", ""
    )
    if policy:
        style_src = next(part for part in policy.split(";") if "style-src" in part)
        assert "'self'" in style_src
    served = admin_client.get("/static/karni/project-theme.css")
    if served.status_code == 200:  # served by staticfiles' view when DEBUG is on
        assert b"".join(served.streaming_content).decode() == BRAND


@pytest.mark.django_db
def test_karni_pages_load_the_project_theme_exactly_once(admin_client: Any, settings: Any) -> None:
    url = reverse("admin:karni_accounts_role_effective_permissions")
    html = admin_client.get(url).content.decode()
    assert html.count("/static/karni/project-theme.css") == 1

    settings.UNFOLD = {**settings.UNFOLD, "STYLES": []}  # a project that dropped Karni's theme
    html = admin_client.get(url).content.decode()
    assert html.count("/static/karni/project-theme.css") == 1
    assert html.index("/static/karni/tokens.css") < html.index("/static/karni/project-theme.css")
