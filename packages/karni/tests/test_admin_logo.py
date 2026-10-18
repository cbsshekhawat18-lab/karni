"""``KARNI_ADMIN_LOGO``: no logo by default, Karni's mark on request, a project's own paths."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.staticfiles import finders

from karni.conf import karni_settings
from karni.conf.admin_logo import KARNI_MARK, unfold_logo_entries
from karni.exceptions import KarniImproperlyConfigured


def _settings(**overrides: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev", **overrides)
    return namespace


def test_no_logo_by_default() -> None:
    unfold = _settings()["UNFOLD"]
    assert "SITE_LOGO" not in unfold and "SITE_ICON" not in unfold
    assert unfold_logo_entries(None) == {} and unfold_logo_entries("") == {}


@pytest.mark.django_db
def test_karni_mark_is_shipped_as_static_files() -> None:
    for path in KARNI_MARK.values():
        assert finders.find(path), path
    unfold = _settings(KARNI_ADMIN_LOGO="karni")["UNFOLD"]
    assert unfold["SITE_LOGO"]["light"](None).endswith("/karni/brand/karni-mark.svg")
    assert unfold["SITE_LOGO"]["dark"](None).endswith("/karni/brand/karni-mark-light.svg")
    assert unfold["SITE_ICON"]["light"](None).endswith("/karni/brand/karni-mark-simple.svg")


def test_project_paths_with_fallbacks() -> None:
    entries = unfold_logo_entries({"light": "img/mark.svg"})
    assert entries["SITE_LOGO"]["dark"](None).endswith("/img/mark.svg")
    assert entries["SITE_ICON"]["dark"](None).endswith("/img/mark.svg")
    unfold = _settings(KARNI_ADMIN_LOGO={"light": "img/a.svg", "dark": "img/b.svg"})["UNFOLD"]
    assert unfold["SITE_LOGO"]["dark"](None).endswith("/img/b.svg")


def test_explicit_unfold_keys_win() -> None:
    unfold = _settings(
        KARNI_ADMIN_LOGO="karni", UNFOLD={"SITE_LOGO": "mine.svg", "SITE_TITLE": "Ops"}
    )["UNFOLD"]
    assert unfold["SITE_LOGO"] == "mine.svg" and "SITE_ICON" in unfold


def test_bad_declaration_is_e303() -> None:
    with pytest.raises(KarniImproperlyConfigured, match="E303"):
        unfold_logo_entries({"dark": "x.svg"})
    with pytest.raises(KarniImproperlyConfigured, match="E303"):
        unfold_logo_entries(["karni"])
