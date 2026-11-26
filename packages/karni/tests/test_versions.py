"""``karni.W521``: karni, karni-cli and the first-party modules on one version line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from karni import versions

REPO = Path(versions.__file__).resolve().parents[3]


class _Dist:
    def __init__(self, version: str, direct_url: dict[str, Any] | None = None) -> None:
        self.version = version
        self._direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        return json.dumps(self._direct_url) if self._direct_url is not None else None


def _installed(monkeypatch: pytest.MonkeyPatch, dists: dict[str, _Dist]) -> None:
    def distribution(name: str) -> _Dist:
        if name not in dists:
            raise versions.metadata.PackageNotFoundError(name)
        return dists[name]

    monkeypatch.setattr(versions.metadata, "distribution", distribution)


def test_the_line_and_the_range_of_a_version() -> None:
    assert versions.line("0.7.3") == (0, 7)
    assert versions.line("1.2.0rc1") == (1, 2)
    assert versions.line("nonsense") is None
    assert versions.range_for("0.7.3") == ">=0.7,<0.8"
    assert versions.range_for("1.2.0") == ">=1.2,<2"
    assert versions.range_for("0+unknown") == ">=0.0,<0.1"


def test_the_packages_off_karnis_line_are_named() -> None:
    found = {"karni": "0.7.1", "karni-site": "0.6.2", "karni-ai": "0.7.0", "karni-cli": "0.8.0"}
    assert versions.off_the_line(found, "0.7.1") == {"karni-site": "0.6.2", "karni-cli": "0.8.0"}
    assert versions.off_the_line(found, "not a version") == {}


def test_the_check_warns_once_and_names_each_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        versions,
        "installed_versions",
        lambda: {
            "karni": "0.7.1",
            "karni-site": "0.6.2",
            "karni-cli": "0.8.0",
            "karni-ai": "0.7.0",
        },
    )
    (message,) = versions.check_version_line()
    assert message.id == "karni.W521"
    assert "karni-site 0.6.2" in message.msg and "karni-cli 0.8.0" in message.msg
    assert "karni-ai" not in message.msg
    assert ">=0.7,<0.8" in (message.hint or "") and "karni upgrade" in (message.hint or "")


def test_the_check_is_quiet_on_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        versions, "installed_versions", lambda: {"karni": "0.7.0", "karni-site": "0.7.4"}
    )
    assert versions.check_version_line() == []


def test_a_checkout_is_never_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(
        monkeypatch,
        {
            "karni": _Dist("0.7.0"),
            "karni-site": _Dist("0.6.0", {"dir_info": {"editable": True}}),
            "karni-ai": _Dist("0.6.0.dev3"),
            "karni-game": _Dist("0.6.0+local"),
            "karni-storage": _Dist("0.6.0", {"url": "file:///x", "dir_info": {}}),
        },
    )
    assert versions.installed_versions() == {"karni": "0.7.0", "karni-storage": "0.6.0"}


def test_a_third_party_module_is_not_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch, {"karni": _Dist("0.7.0"), "karni-someone-elses": _Dist("3.0.0")})
    assert versions.installed_versions() == {"karni": "0.7.0"}


@pytest.mark.skipif(not (REPO / "modules").is_dir(), reason="needs the repository checkout")
def test_the_list_is_the_modules_of_the_repository() -> None:
    folders = {path.name for path in (REPO / "modules").iterdir() if path.is_dir()}
    assert set(versions.LOCKSTEP) == {"karni", "karni-cli", *folders}


def test_the_check_is_registered() -> None:
    from django.core.checks.registry import registry

    assert versions.check_version_line in registry.registered_checks
