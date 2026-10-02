from __future__ import annotations

import json
import subprocess
from pathlib import Path

from karni_cli import project as project_mod
from karni_cli.commands.context import (
    apps_line,
    assemble,
    find_manifest,
    manifest_lines,
    pages_line,
)
from karni_cli.main import app

BACKEND = (
    "MODELS: Event(title,starts_at,capacity,status) Venue(name,address)\n"
    "VIEWSETS: EventViewSet VenueViewSet\n"
    "MODULES: payments\n"
    "BASES: BaseModel SoftDeleteModel BaseViewSet KarniModelAdmin AbstractKarniUser"
)


def test_assemble_orders_sections() -> None:
    out = assemble(BACKEND, ["COMPONENTS: Page ResourceTable", "HOOKS: useAuth"])
    lines = out.split("\n")
    assert [line.split(":")[0] for line in lines] == [
        "MODELS",
        "VIEWSETS",
        "COMPONENTS",
        "HOOKS",
        "MODULES",
        "BASES",
    ]


def test_assemble_without_manifest_omits_ui_lines() -> None:
    out = assemble(BACKEND, [])
    assert "COMPONENTS" not in out and "HOOKS" not in out


def test_manifest_lines(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"components": ["ResourceTable", "Page"], "hooks": ["useAuth"]}))
    assert manifest_lines(manifest) == [
        "COMPONENTS: Page ResourceTable",
        "HOOKS: useAuth",
    ]


def test_find_manifest_prefers_frontend(tmp_path: Path) -> None:
    target = tmp_path / "frontend" / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    assert find_manifest(tmp_path, None) == target
    assert find_manifest(tmp_path, tmp_path / "nope.json") is None


def test_cli_end_to_end_with_mocked_backend(runner, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == BACKEND


def test_budget_for_ten_model_project() -> None:
    models = " ".join(f"Model{i}(alpha,beta,gamma,delta)" for i in range(10))
    output = assemble(
        f"MODELS: {models}\nVIEWSETS: "
        + " ".join(f"Model{i}ViewSet" for i in range(10))
        + "\nBASES: BaseModel SoftDeleteModel BaseViewSet KarniModelAdmin AbstractKarniUser",
        [],
    )
    assert len(output) < 800


def test_apps_and_pages_are_read_statically(generated_project: Path) -> None:
    settings = generated_project / "config" / "settings.py"
    settings.write_text(
        settings.read_text().replace(
            '    # "myapp",\n',
            '    # "commented",\n    "events",\n    "apps.billing.apps.BillingConfig",\n'
            '    "karni_payments",\n',
        )
    )
    (generated_project / "events").mkdir()
    (generated_project / "apps" / "billing").mkdir(parents=True)
    assert apps_line(generated_project) == "APPS: events(events/) billing(apps/billing/)"

    pages = generated_project / "frontend" / "src" / "pages"
    (pages / "events").mkdir(parents=True)
    (pages / "home.tsx").write_text("")
    (pages / "events" / "edit.tsx").write_text("")
    (pages / "home.test.tsx").write_text("")
    assert pages_line(generated_project) == "PAGES: events/edit home"


def test_context_prepends_apps_and_appends_pages(
    runner, generated_project: Path, monkeypatch
) -> None:
    settings = generated_project / "config" / "settings.py"
    settings.write_text(settings.read_text().replace('    # "myapp",\n', '    "events",\n'))
    (generated_project / "events").mkdir()
    # The scaffold ships frontend/src/pages/ (home.tsx) already.
    (generated_project / "frontend" / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (generated_project / "frontend" / "src" / "pages" / "events.tsx").write_text("")
    monkeypatch.chdir(generated_project)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=BACKEND + "\n", stderr=""),
    )
    result = runner.invoke(app, ["context"])
    assert result.exit_code == 0, result.output
    keys = [line.split(":")[0] for line in result.output.strip().split("\n")]
    assert keys == ["APPS", "MODELS", "VIEWSETS", "PAGES", "MODULES", "BASES"]


def test_context_failure_exits_nonzero(runner, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 3, stdout="", stderr="boom\n"),
    )
    assert runner.invoke(app, ["context"]).exit_code == 1
