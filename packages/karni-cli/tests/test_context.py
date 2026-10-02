from __future__ import annotations

import json
import subprocess
from pathlib import Path

from karni_cli import project as project_mod
from karni_cli.commands.context import assemble, find_manifest, manifest_lines
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
