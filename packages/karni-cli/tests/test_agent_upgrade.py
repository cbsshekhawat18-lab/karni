"""The `karni upgrade` codemod: old hand-written agent files -> rules + adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

import karni_cli.commands.upgrade as upgrade_mod
from karni_cli import agent_data
from karni_cli.adapters import GENERATED_MARK, sync
from karni_cli.main import app
from karni_cli.upgrades.legacy_agent_files import LEGACY_FILES, PROJECT_NAME
from karni_cli.upgrades.v0_2.agent_guidance import CODEMOD, migrate_agent_guidance, plan

FRAGMENT = "## Payments (karni-payments)\n- Never call provider SDKs directly."


def _write_legacy(project: Path, files: dict[str, str] | None = None) -> None:
    """Replace the generated adapters with the pre-retrofit scaffold files."""
    for path in project.rglob("*"):
        if path.is_file() and GENERATED_MARK in path.read_text(errors="replace"):
            path.unlink()
    for rel, text in (files or LEGACY_FILES).items():
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.replace(PROJECT_NAME, "Acme Board"))


def _customised() -> dict[str, str]:
    files = dict(LEGACY_FILES)
    agents = files["AGENTS.md"]
    agents = agents.replace(
        "- Models inherit `karni.models.BaseModel` (or `SoftDeleteModel`).\n",
        "- Models inherit `karni.models.BaseModel` (or `SoftDeleteModel`).\n"
        "- Money is always a Decimal, never a float.\n",
    )
    agents = agents.replace("- After any model change: `make migrate && karni types`.\n", "")
    agents += (
        "\n## Billing\n- Invoices are immutable once sent.\n  Credit notes reverse them.\n"
        f"\n<!-- karni:module:payments -->\n{FRAGMENT}\n<!-- /karni:module:payments -->\n"
    )
    files["AGENTS.md"] = agents
    files[".claude/commands/new-model.md"] += "6. Add a factory in tests/factories.py.\n"
    return files


def test_unmodified_legacy_project_migrates_cleanly(generated_project: Path) -> None:
    _write_legacy(generated_project)
    changed = migrate_agent_guidance(generated_project, dry_run=False)
    assert not (generated_project / "karni.rules.py").exists()  # nothing project-specific
    assert not (generated_project / ".cursorrules").exists()
    for rel in LEGACY_FILES:
        assert (generated_project / ".karni" / "backup" / rel).is_file(), rel
    assert "AGENTS.md" in changed
    assert sync(generated_project, agent_data.load(generated_project), check=True).stale == []


def test_project_additions_are_preserved_verbatim(
    generated_project: Path, runner, monkeypatch
) -> None:
    _write_legacy(generated_project, _customised())
    migrate_agent_guidance(generated_project, dry_run=False)

    rules_file = (generated_project / "karni.rules.py").read_text()
    assert "# REVIEW: removed from Karni's guidance in AGENTS.md: - After any model change" in (
        rules_file
    )
    data = agent_data.load(generated_project)
    project_rules = {r["code"]: r for r in data.rules if r["code"].startswith("P")}
    texts = {r["rule"]: r["category"] for r in project_rules.values()}
    assert texts == {
        "Money is always a Decimal, never a float.": "project-always",
        "Invoices are immutable once sent. Credit notes reverse them.": "project-billing",
        "(.claude/commands/new-model.md) Add a factory in tests/factories.py.": "project",
    }
    assert sorted(project_rules) == ["P001", "P002", "P003"]

    module = generated_project / ".karni" / "modules" / "payments.md"
    assert module.read_text() == FRAGMENT + "\n"
    agents = (generated_project / "AGENTS.md").read_text()
    assert GENERATED_MARK in agents and "<!-- karni:module:payments -->" in agents
    backup = (generated_project / ".karni" / "backup" / "AGENTS.md").read_text()
    assert "Money is always a Decimal" in backup

    monkeypatch.chdir(generated_project)
    listing = runner.invoke(app, ["rules"])
    assert "P001 Money is always a Decimal, never a float." in listing.output
    assert "[module:payments]" in listing.output
    check = runner.invoke(app, ["rules", "sync", "--check"])
    assert check.exit_code == 0, check.output

    # Idempotent: the second run finds only generated files.
    assert migrate_agent_guidance(generated_project, dry_run=False) == []


def test_dry_run_changes_nothing(generated_project: Path) -> None:
    _write_legacy(generated_project, _customised())
    before = {p: p.read_bytes() for p in generated_project.rglob("*") if p.is_file()}
    changed = migrate_agent_guidance(generated_project, dry_run=True)
    after = {p: p.read_bytes() for p in generated_project.rglob("*") if p.is_file()}
    assert before == after
    assert {"karni.rules.py", "AGENTS.md", ".karni/modules/payments.md"} <= set(changed)


def test_existing_rules_file_is_appended_not_overwritten(generated_project: Path) -> None:
    _write_legacy(generated_project, _customised())
    (generated_project / "karni.rules.py").write_text(
        'ADD = [{"code": "P001", "rule": "Ours already."}]\n'
    )
    migrate_agent_guidance(generated_project, dry_run=False)
    text = (generated_project / "karni.rules.py").read_text()
    assert text.startswith('ADD = [{"code": "P001", "rule": "Ours already."}]')
    codes = [r["code"] for r in agent_data.load(generated_project).rules]
    assert sorted(c for c in codes if c.startswith("P")) == ["P001", "P002", "P003", "P004"]


def test_claude_md_as_source_of_truth_variant(generated_project: Path) -> None:
    """Early phase-8 projects kept the full guidance in CLAUDE.md, no AGENTS.md."""
    legacy = {"CLAUDE.md": LEGACY_FILES["AGENTS.md"] + "- Deploys go through `make ship`.\n"}
    _write_legacy(generated_project, legacy)
    migrate_agent_guidance(generated_project, dry_run=False)
    rules = [r["rule"] for r in agent_data.load(generated_project).rules]
    assert "Deploys go through `make ship`." in rules
    assert (generated_project / "CLAUDE.md").read_text().splitlines()[-1] == "@AGENTS.md"


def test_foreign_files_are_left_alone(generated_project: Path, capsys) -> None:
    _write_legacy(generated_project, {"CLAUDE.md": "# Team handbook\n\nUse tabs.\n"})
    changed = migrate_agent_guidance(generated_project, dry_run=False)
    assert changed == []
    assert (generated_project / "CLAUDE.md").read_text() == "# Team handbook\n\nUse tabs.\n"
    assert "does not look like Karni's file" in capsys.readouterr().out
    assert plan(generated_project).foreign == ["CLAUDE.md"]


def test_cli_upgrade_runs_the_codemod(runner, generated_project: Path, monkeypatch) -> None:
    _write_legacy(generated_project, _customised())
    monkeypatch.chdir(generated_project)
    monkeypatch.setattr(upgrade_mod, "_installed_version", lambda *a: "0.1.0")
    listed = runner.invoke(app, ["upgrade", "--list"])
    assert "agent-guidance-files" in listed.output
    assert "codemod v0_2.agent_guidance" in listed.output
    preview = runner.invoke(app, ["upgrade", "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert "+++ b/karni.rules.py" in preview.output  # a real diff, nothing written
    assert not (generated_project / "karni.rules.py").exists()
    # The generated project is not a git repository: writing needs --allow-dirty.
    refused = runner.invoke(app, ["upgrade"])
    assert refused.exit_code != 0
    result = runner.invoke(app, ["upgrade", "--allow-dirty"])
    assert result.exit_code == 0, result.output
    assert "REVIEW: you removed" in result.output
    assert "karni.rules.py: 1" in result.output
    assert GENERATED_MARK in (generated_project / "AGENTS.md").read_text()
    assert (generated_project / ".karni" / "backup" / "AGENTS.md").is_file()


def test_the_codemod_reports_review_notes_as_sites(generated_project: Path) -> None:
    _write_legacy(generated_project, _customised())
    outcome = CODEMOD.apply(generated_project)
    assert "karni.rules.py" in outcome.files
    notes = [site.render() for site in outcome.sites]
    assert any(n.startswith("AGENTS.md: REVIEW: you removed") for n in notes), notes
    assert CODEMOD.apply(generated_project).files == {}  # idempotent


@pytest.mark.parametrize("rel", sorted(LEGACY_FILES))
def test_each_legacy_file_is_recognised(rel: str, generated_project: Path) -> None:
    _write_legacy(generated_project, {rel: LEGACY_FILES[rel]})
    assert plan(generated_project).migrated == [rel]
