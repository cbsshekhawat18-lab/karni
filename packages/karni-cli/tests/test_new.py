from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from karni_cli import scaffold, toolchain
from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.scaffold import (
    UI_DIST_FILES,
    derive_slug,
    resolve_template,
    resolve_ui_source,
    ui_mount_target,
    ui_spec,
    validate_name,
)

from .conftest import REPO_ROOT, TEMPLATE


def test_new_generates_project(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = runner.invoke(app, ["new", "My App", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    project = tmp_path / "my_app"
    for expected in ("manage.py", "config/settings.py", "docker-compose.yml", "AGENTS.md"):
        assert (project / expected).exists(), expected
    assert "# karni:apps" in (project / "config" / "settings.py").read_text()
    # next steps must print the SLUG, not the input name
    assert "cd my_app" in result.output
    # the release the scaffold is written for: `karni upgrade` starts there
    assert 'baseline = "0.4.0"' in (project / "pyproject.toml").read_text()


def test_new_project_installs_with_pip_install_e(runner, tmp_path: Path, monkeypatch) -> None:
    """The README's `pip install -e .` installs the dependencies, not a package.

    Without a declared build system and `packages = []`, setuptools' discovery
    refused the flat layout ("Multiple top-level packages discovered in a
    flat-layout: ['config', 'frontend']").
    """
    import tomllib

    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = runner.invoke(app, ["new", "Shop", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    pyproject = tomllib.loads((tmp_path / "shop" / "pyproject.toml").read_text())
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["packages"] == []
    assert "pip install -e ." in (tmp_path / "shop" / "README.md").read_text()


def test_slug_rules() -> None:
    assert derive_slug("My App") == "my_app"
    assert validate_name("acme-board") == "acme_board"
    with pytest.raises(CliError):
        validate_name("my.app")
    with pytest.raises(CliError):
        validate_name("1weird")


def test_repo_walk_resolution(monkeypatch) -> None:
    monkeypatch.delenv("KARNI_TEMPLATES", raising=False)
    assert resolve_template() == TEMPLATE


# @karni/ui source: KARNI_UI_SRC > monorepo checkout > npm registry


def _fake_ui(root: Path, *, built: bool = True, name: str = "@karni/ui") -> Path:
    ui = root / "packages" / "karni-ui"
    (ui / "src").mkdir(parents=True)
    (ui / "src" / "index.ts").write_text("export {};\n")
    (ui / "package.json").write_text(json.dumps({"name": name, "version": "0.1.0"}))
    (root / "packages" / "karni").mkdir()
    if built:
        for rel in UI_DIST_FILES:
            (ui / rel).parent.mkdir(parents=True, exist_ok=True)
            (ui / rel).write_text("")
    return ui


def _frontend_volumes(project: Path) -> list[object]:
    compose = yaml.safe_load((project / "docker-compose.yml").read_text())
    return compose["services"]["frontend"]["volumes"]


def test_ui_source_env_override(tmp_path: Path, monkeypatch) -> None:
    ui = _fake_ui(tmp_path)
    monkeypatch.setenv("KARNI_UI_SRC", str(ui))
    assert resolve_ui_source() == ui.resolve()
    monkeypatch.setenv("KARNI_UI_SRC", str(tmp_path / "packages" / "karni"))
    with pytest.raises(CliError, match="KARNI_UI_SRC"):
        resolve_ui_source()


def test_ui_source_repo_walk_finds_this_checkout() -> None:
    assert resolve_ui_source() == REPO_ROOT / "packages" / "karni-ui"


def test_ui_source_repo_walk_is_verified(tmp_path: Path) -> None:
    start = tmp_path / "packages" / "karni-cli" / "karni_cli" / "scaffold.py"
    ui = _fake_ui(tmp_path)
    assert resolve_ui_source(start) == ui
    (tmp_path / "packages" / "karni").rmdir()  # not a Karni monorepo
    assert resolve_ui_source(start) is None
    (tmp_path / "packages" / "karni").mkdir()
    (ui / "package.json").write_text(json.dumps({"name": "some-other-ui"}))
    assert resolve_ui_source(start) is None


def test_ui_spec(tmp_path: Path) -> None:
    assert ui_spec(None) == "^0.4.0"
    assert ui_spec(Path("/opt/Karni/packages/karni-ui")) == "file:/opt/Karni/packages/karni-ui"
    # A project elsewhere keeps the absolute path; one inside the checkout gets a
    # relative one (from frontend/), so examples/ install on any machine.
    ui = tmp_path / "Karni" / "packages" / "karni-ui"
    assert ui_spec(ui, tmp_path / "elsewhere" / "proj") == f"file:{ui}"
    inside = ui_spec(ui, tmp_path / "Karni" / "examples" / "demo")
    assert inside == "file:../../../packages/karni-ui"


def test_new_writes_a_local_ui_dependency(runner, tmp_path: Path, monkeypatch) -> None:
    ui = _fake_ui(tmp_path / "karni")
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("KARNI_UI_SRC", str(ui))
    result = runner.invoke(app, ["new", "Local UI", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    project = tmp_path / "out" / "local_ui"
    package = json.loads((project / "frontend" / "package.json").read_text())
    assert package["dependencies"]["@karni/ui"] == f"file:{ui.resolve()}"
    assert "optionalDependencies" not in package
    assert "install-links=true" in (project / "frontend" / ".npmrc").read_text()
    mount = {"type": "bind", "source": str(ui.resolve()), "target": str(ui.resolve()),
             "read_only": True}  # fmt: skip
    assert mount in _frontend_volumes(project)
    assert f"@karni/ui: file:{ui.resolve()}" in result.output
    assert "Building @karni/ui" not in result.output


def test_new_inside_the_checkout_uses_a_relative_ui_path(
    runner, tmp_path: Path, monkeypatch
) -> None:
    ui = _fake_ui(tmp_path / "karni")
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("KARNI_UI_SRC", str(ui))
    examples = tmp_path / "karni" / "examples"
    result = runner.invoke(app, ["new", "Demo", "-o", str(examples)])
    assert result.exit_code == 0, result.output
    package = json.loads((examples / "demo" / "frontend" / "package.json").read_text())
    assert package["dependencies"]["@karni/ui"] == "file:../../../packages/karni-ui"
    mount = {"type": "bind", "source": "../../../packages/karni-ui",
             "target": "/packages/karni-ui", "read_only": True}  # fmt: skip
    assert mount in _frontend_volumes(examples / "demo")
    assert "@karni/ui: file:../../../packages/karni-ui" in result.output


def test_ui_mount_target() -> None:
    assert ui_mount_target("file:/opt/Karni/packages/karni-ui") == "/opt/Karni/packages/karni-ui"
    assert ui_mount_target("file:../../../packages/karni-ui") == "/packages/karni-ui"
    assert ui_mount_target("^0.1.0") == "^0.1.0"


def test_new_falls_back_to_the_registry(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setattr(scaffold, "resolve_ui_source", lambda: None)
    result = runner.invoke(app, ["new", "Registry UI", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    project = tmp_path / "registry_ui"
    package = json.loads((project / "frontend" / "package.json").read_text())
    assert package["dependencies"]["@karni/ui"] == "^0.4.0"
    assert all(isinstance(volume, str) for volume in _frontend_volumes(project))
    assert "KARNI_UI_SRC=" in result.output


def test_new_frontend_requires_npm_11(runner, tmp_path: Path, monkeypatch) -> None:
    """npm 10 crashes on a fresh install of this frontend, so the scaffold asks for npm 11.

    npm checks engines only after the dependency walk that crashes, so engine-strict
    stops npm 10 only once a package-lock.json exists. The next steps name the fix
    for the fresh install.
    """
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setattr(scaffold, "resolve_ui_source", lambda: None)
    result = runner.invoke(app, ["new", "Engines", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    frontend = tmp_path / "engines" / "frontend"
    package = json.loads((frontend / "package.json").read_text())
    assert package["engines"] == {"node": ">=20.19", "npm": f">={toolchain.NPM_FLOOR}"}
    settings = [
        line for line in (frontend / ".npmrc").read_text().splitlines() if not line.startswith("#")
    ]
    assert "install-links=true" in settings and "engine-strict=true" in settings
    assert "npx npm@11 install" in result.output


def test_new_builds_a_missing_ui_dist(runner, tmp_path: Path, monkeypatch) -> None:
    ui = _fake_ui(tmp_path / "karni", built=False)
    calls: list[list[str]] = []

    def fake_npm(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert cwd == ui.resolve()
        if argv[1:] == ["run", "build"]:
            for rel in UI_DIST_FILES:
                (cwd / rel).parent.mkdir(parents=True, exist_ok=True)
                (cwd / rel).write_text("")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(scaffold, "run_npm", fake_npm)
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("KARNI_UI_SRC", str(ui))
    result = runner.invoke(app, ["new", "Built UI", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert calls == [["npm", "install", "--no-audit", "--no-package-lock"], ["npm", "run", "build"]]
    assert "Building @karni/ui" in result.output and "warning" not in result.output
    assert "node_modules/ and dist/" in result.output


def test_a_locked_ui_installs_with_npm_ci(tmp_path: Path) -> None:
    ui = _fake_ui(tmp_path, built=False)
    (ui / "package-lock.json").write_text("{}")
    assert scaffold.ui_build_commands(ui) == [["npm", "ci", "--no-audit"], ["npm", "run", "build"]]


@pytest.mark.skipif(
    os.environ.get("KARNI_TEST_UI_BUILD") != "1",
    reason="builds @karni/ui for real in a clone (npm ci + vite, about a minute, network); "
    "set KARNI_TEST_UI_BUILD=1 to run it (CI's Quickstart job does)",
)
def test_new_from_a_checkout_leaves_git_status_clean(tmp_path: Path) -> None:
    """``karni new`` run from a clone builds that clone's @karni/ui and changes no tracked file."""
    clone = tmp_path / "karni"
    git = ["git", "-C", str(clone)]
    # init + fetch HEAD, not clone: CI checks a pull request out as a detached commit
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run([*git, "fetch", "-q", "--depth", "1", f"file://{REPO_ROOT}", "HEAD"], check=True)
    subprocess.run([*git, "checkout", "-q", "FETCH_HEAD"], check=True)
    ui = clone / "packages" / "karni-ui"
    assert not (ui / "dist").exists() and not (ui / "node_modules").exists()
    env = {k: v for k, v in os.environ.items() if k not in {"KARNI_UI_SRC", "KARNI_TEMPLATES"}}
    env["PYTHONPATH"] = str(clone / "packages" / "karni-cli")  # the clone's CLI finds the clone
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from karni_cli.main import app; app(prog_name='karni')",
            "new",
            "Clean Check",
            "-o",
            str(tmp_path / "out"),
        ],
        cwd=clone,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Building @karni/ui in {ui}" in result.stdout
    assert (ui / "dist" / "index.js").is_file(), "the clone's @karni/ui was not built"
    status = subprocess.run(
        [*git, "status", "--porcelain"], text=True, capture_output=True, check=True
    )
    assert status.stdout == "", f"karni new changed the checkout:\n{status.stdout}"


def test_new_warns_when_the_ui_cannot_be_built(runner, tmp_path: Path, monkeypatch) -> None:
    ui = _fake_ui(tmp_path / "karni", built=False)
    (ui / "node_modules").mkdir()  # installed: only the build runs (and fails)
    assert scaffold.ui_build_commands(ui) == [["npm", "run", "build"]]
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("KARNI_UI_SRC", str(ui))
    result = runner.invoke(app, ["new", "Unbuilt UI", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "warning: could not build @karni/ui" in result.output
    assert f"(cd {ui.resolve()} && npm install && npm run build)" in result.output
    assert (tmp_path / "out" / "unbuilt_ui" / "frontend" / "package.json").is_file()


def test_stale_ui_dist_is_reported(tmp_path: Path) -> None:
    ui = _fake_ui(tmp_path)
    assert not scaffold.ui_dist_stale(ui)
    built = (ui / UI_DIST_FILES[0]).stat().st_mtime
    os.utime(ui / "src" / "index.ts", (built + 10, built + 10))
    assert scaffold.ui_dist_stale(ui)


def test_new_warns_about_a_stale_ui_dist(runner, tmp_path: Path, monkeypatch) -> None:
    ui = _fake_ui(tmp_path / "karni")
    built = (ui / UI_DIST_FILES[0]).stat().st_mtime
    os.utime(ui / "src" / "index.ts", (built + 10, built + 10))
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setenv("KARNI_UI_SRC", str(ui))
    result = runner.invoke(app, ["new", "Stale UI", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "dist is older than its sources" in result.output
    assert "Building @karni/ui" not in result.output
