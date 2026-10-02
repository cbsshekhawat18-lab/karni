from __future__ import annotations

from pathlib import Path

from packaging.specifiers import SpecifierSet

import karni_cli.commands.upgrade as upgrade_mod
from karni_cli.main import app
from karni_cli.upgrades import Upgrade, applicable


def test_empty_registry_short_circuits_without_probe(runner, tmp_path, monkeypatch) -> None:
    # no manage.py, no project — must still succeed because nothing is registered
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upgrade_mod, "UPGRADES", [])
    called = False

    def probe(*a, **k):
        nonlocal called
        called = True
        return "0.1.0"

    monkeypatch.setattr(upgrade_mod, "_installed_version", probe)
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert "no mechanical migrations registered" in result.output
    assert called is False

    assert runner.invoke(app, ["upgrade", "--list"]).exit_code == 0


def test_applicable_selection_and_ordering() -> None:
    changed: list[str] = []

    def apply(root: Path, dry_run: bool) -> list[str]:
        changed.append(str(dry_run))
        return ["a.py"]

    upgrades = [
        Upgrade(SpecifierSet(">=0.2,<0.3"), "0.3.0", "b", apply),
        Upgrade(SpecifierSet(">=0.1,<0.2"), "0.2.0", "a", apply),
        Upgrade(SpecifierSet(">=0.1,<0.3"), "0.2.5", "c", apply),
    ]
    import karni_cli.upgrades as reg

    original = reg.UPGRADES[:]
    reg.UPGRADES[:] = upgrades
    try:
        selected = applicable("0.1.4")
        assert [u.to_version for u in selected] == ["0.2.0", "0.2.5"]
        assert applicable("0.2.1") and applicable("0.2.1")[0].to_version == "0.2.5"
    finally:
        reg.UPGRADES[:] = original
