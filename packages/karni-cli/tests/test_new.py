from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from karni_cli import scaffold, toolchain
from karni_cli.commands import new as new_mod
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
    assert 'baseline = "0.5.0"' in (project / "pyproject.toml").read_text()
    # generators insert project routes at this marker (karni make site)
    assert (
        "    # karni:urls\n    # Only while DEBUG" in (project / "config" / "urls.py").read_text()
    )


def test_new_into_an_existing_folder_is_a_coded_error(runner, tmp_path: Path, monkeypatch) -> None:
    """F14: cookiecutter's own OutputDirExistsException used to reach the user."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    (tmp_path / "my_app").mkdir()
    (tmp_path / "my_app" / "keep.txt").write_text("mine")
    result = runner.invoke(app, ["new", "My App", "-o", str(tmp_path)])
    assert isinstance(result.exception, CliError) and "C850" in str(result.exception)
    assert "OutputDirExists" not in repr(result.exception)
    assert (tmp_path / "my_app" / "keep.txt").read_text() == "mine"


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


def test_new_stores_files_under_the_project_and_on_the_volume_in_containers(
    runner, tmp_path: Path, monkeypatch
) -> None:
    """A host run (karni serve --local) uses data/ under the project, a container /data."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = runner.invoke(app, ["new", "Files", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    project = tmp_path / "files"
    active = [
        line
        for line in (project / ".env.example").read_text().splitlines()
        if line.startswith(("MEDIA_ROOT=", "STATIC_ROOT="))
    ]
    assert active == [], "an active /data line in .env breaks a host run"
    dockerfile = (project / "Dockerfile").read_text()
    assert dockerfile.count("MEDIA_ROOT=/data/media") == 2  # the base (dev) and prod stages
    assert dockerfile.count("STATIC_ROOT=/data/static") == 2
    assert "/data/" in (project / ".gitignore").read_text().splitlines()


def test_the_env_example_shows_the_phone_country_and_the_mail_server(
    runner, tmp_path: Path, monkeypatch
) -> None:
    """Both env files name the settings whose format a project cannot guess, commented."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = runner.invoke(
        app, ["new", "Shop", "--domain", "shop.example.net", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    project = tmp_path / "shop"
    example = (project / ".env.example").read_text()
    for line in (
        "# KARNI_PHONE_COUNTRY_CODE=44",
        "# KARNI_PHONE_TRUNK_PREFIX=0",
        "# EMAIL_URL=smtp://localhost:1025",
        "# DEFAULT_FROM_EMAIL=noreply@shop.example.net",
    ):
        assert f"\n{line}\n" in example, line
    assert '"44" for the UK (not "GB")' in example
    production = (project / ".env.prod.example").read_text()
    assert "\n# KARNI_PHONE_COUNTRY_CODE=44\n" in production
    assert "\n# DEFAULT_FROM_EMAIL=noreply@shop.example.net\n" in production


def test_the_frontend_has_no_known_vulnerable_zod(runner, tmp_path: Path, monkeypatch) -> None:
    """GHSA-mrhx-c7xc-m3w5: Zod before 4.6.6 (npm audit: high). The scaffold and @karni/ui agree."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    assert runner.invoke(app, ["new", "Shop", "-o", str(tmp_path)]).exit_code == 0
    frontend = json.loads((tmp_path / "shop" / "frontend" / "package.json").read_text())
    assert frontend["dependencies"]["zod"] == "^4.6.6"
    assert frontend["dependencies"]["@hookform/resolvers"].startswith("^5.")  # Zod 4 support
    ui = json.loads((REPO_ROOT / "packages" / "karni-ui" / "package.json").read_text())
    assert "^4.6.6" in ui["peerDependencies"]["zod"].split(" || ")
    assert "^3.23.0" in ui["peerDependencies"]["zod"].split(
        " || "
    )  # projects on Zod 3 keep working
    assert ui["devDependencies"]["zod"] == "^4.6.6"


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
    assert ui_spec(None) == "^0.5.0"
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


def test_a_checkout_found_by_walking_is_used_only_inside_it(
    runner, tmp_path: Path, monkeypatch
) -> None:
    """A CLI run from a checkout must not write that checkout's absolute path elsewhere."""
    monkeypatch.delenv("KARNI_UI_SRC", raising=False)
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    ui = REPO_ROOT / "packages" / "karni-ui"
    assert scaffold.resolve_ui_source_for(tmp_path / "proj") is None
    assert scaffold.resolve_ui_source_for(REPO_ROOT / "examples" / "demo") == ui
    result = runner.invoke(app, ["new", "Elsewhere", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    package = json.loads((tmp_path / "elsewhere" / "frontend" / "package.json").read_text())
    assert package["dependencies"]["@karni/ui"] == "^0.5.0"
    assert "/" not in package["dependencies"]["@karni/ui"]


def test_new_falls_back_to_the_registry(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setattr(scaffold, "resolve_ui_source", lambda: None)
    result = runner.invoke(app, ["new", "Registry UI", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    project = tmp_path / "registry_ui"
    package = json.loads((project / "frontend" / "package.json").read_text())
    assert package["dependencies"]["@karni/ui"] == "^0.5.0"
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


def _isolated_git(monkeypatch, tmp_path: Path, *, hooks: Path | None = None) -> None:
    """git with no user or system config of this machine, and a fixed identity."""
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks}\n" if hooks else "")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Karni Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))


def _git_out(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True, text=True, check=True
    ).stdout


def test_new_makes_a_git_repository_with_a_first_commit(runner, tmp_path, monkeypatch) -> None:
    _isolated_git(monkeypatch, tmp_path)
    out = tmp_path / "out"
    result = runner.invoke(app, ["new", "Bakery", "-o", str(out)])
    assert result.exit_code == 0, result.output
    project = out / "bakery"
    assert (project / ".git").is_dir()
    assert "a git repository with a first commit" in result.output
    assert _git_out(project, "log", "--format=%s").splitlines() == [new_mod.FIRST_COMMIT]
    assert _git_out(project, "status", "--porcelain") == ""  # everything is committed
    tracked = _git_out(project, "ls-files").splitlines()
    assert "manage.py" in tracked and ".env.example" in tracked and ".env" not in tracked


def test_no_git_and_an_existing_repository_leave_git_alone(runner, tmp_path, monkeypatch) -> None:
    _isolated_git(monkeypatch, tmp_path)
    skipped = runner.invoke(app, ["new", "Plain", "-o", str(tmp_path / "a"), "--no-git"])
    assert skipped.exit_code == 0, skipped.output
    assert not (tmp_path / "a" / "plain" / ".git").exists()
    outer = tmp_path / "monorepo"
    outer.mkdir()
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    inside = runner.invoke(app, ["new", "Inner", "-o", str(outer / "apps")])
    assert inside.exit_code == 0, inside.output
    assert not (outer / "apps" / "inner" / ".git").exists()
    assert f"inside the git repository at {outer.resolve()}" in inside.output


def test_a_refused_first_commit_says_how_to_finish(runner, tmp_path, monkeypatch) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho 'refused by policy' >&2\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    _isolated_git(monkeypatch, tmp_path, hooks=hooks)
    result = runner.invoke(app, ["new", "Refused", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    project = tmp_path / "out" / "refused"
    assert (project / ".git").is_dir()
    assert "the first commit failed (refused by policy)" in result.output
    assert f"git add -A && git commit -m '{new_mod.FIRST_COMMIT}'" in result.output


def test_without_git_on_path_the_project_is_still_made(runner, tmp_path, monkeypatch) -> None:
    _isolated_git(monkeypatch, tmp_path)
    real_which = shutil.which
    monkeypatch.setattr(
        new_mod.shutil, "which", lambda cmd, *a, **k: None if cmd == "git" else real_which(cmd)
    )
    result = runner.invoke(app, ["new", "No Git", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "git is not installed, so the project is not a git repository" in result.output
    assert not (tmp_path / "out" / "no_git" / ".git").exists()


def test_a_new_project_ignores_what_pip_install_leaves(runner, tmp_path: Path, monkeypatch) -> None:
    """The README's `pip install -e .` writes <slug>.egg-info: not an untracked file."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setattr(scaffold, "resolve_ui_source", lambda: None)
    result = runner.invoke(app, ["new", "Egg Info", "-o", str(tmp_path), "--no-git"])
    assert result.exit_code == 0, result.output
    ignored = (tmp_path / "egg_info" / ".gitignore").read_text().splitlines()
    assert "*.egg-info/" in ignored and "__pycache__/" in ignored


def test_a_new_project_starts_without_the_legacy_cache_header(
    runner, tmp_path: Path, monkeypatch
) -> None:
    """A fresh app sends only X-Cache, so its first run has no deprecation warning."""
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    monkeypatch.setattr(scaffold, "resolve_ui_source", lambda: None)
    result = runner.invoke(app, ["new", "Quiet Cache", "-o", str(tmp_path), "--no-git"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "quiet_cache" / "config" / "settings.py").read_text()
    assert (
        'KARNI_API_CACHE_LEGACY_HEADER = env.bool("KARNI_API_CACHE_LEGACY_HEADER", default=False)'
        in text
    )
    assert text.index("karni_settings(globals())") < text.index("KARNI_API_CACHE_LEGACY_HEADER")
