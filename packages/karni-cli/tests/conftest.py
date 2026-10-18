from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = REPO_ROOT / "templates" / "project"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def generated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real cookiecutter render of the repo template."""
    from cookiecutter.main import cookiecutter

    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    cookiecutter(
        str(TEMPLATE),
        no_input=True,
        extra_context={"project_name": "Acme Board"},
        output_dir=str(tmp_path),
    )
    project = tmp_path / "acme_board"
    assert project.is_dir()
    # Mirror `karni new`: the template carries no agent files; they are generated.
    from karni_cli.commands.new import write_agent_adapters

    write_agent_adapters(project)
    return project


@pytest.fixture(autouse=True)
def _no_ambient_templates_env(monkeypatch: pytest.MonkeyPatch):
    for var in ("KARNI_TEMPLATES", "KARNI_AGENT_SOURCE", "KARNI_UI_SRC"):
        if var in os.environ:
            monkeypatch.delenv(var)


@pytest.fixture(autouse=True)
def _no_active_virtualenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite's expectations are for a project without an interpreter around it."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)


@pytest.fixture(autouse=True)
def _no_npm(monkeypatch: pytest.MonkeyPatch) -> None:
    """`karni new` never runs npm in the suite (an unbuilt checkout would build @karni/ui).

    The stub fails like a missing npm, so `karni new` warns and carries on;
    tests of the build path replace it.
    """
    from karni_cli import scaffold

    def no_npm(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 127, stdout="", stderr="npm disabled in tests")

    monkeypatch.setattr(scaffold, "run_npm", no_npm)


# history providers: the suite runs with none, and none spawns anything

HISTORY_MARKER = "history_provider"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", f"{HISTORY_MARKER}: the test runs a history provider's subprocess on purpose"
    )


def _spawns_chronicle(args: Any) -> bool:
    argv0 = args[0] if isinstance(args, list | tuple) and args else str(args).split(" ")[0]
    return Path(str(argv0)).name.split(".")[0] == "chronicle"


def _chronicle_classes() -> list[type]:
    """The built-in provider class as karni and as the karni-cli bundle load it."""
    from karni_cli import agent_data

    classes: list[type] = []
    for package in ("karni.agent", None):
        try:
            if package is None:
                bundled = agent_data._bundled()
                if bundled is None:
                    continue
                package = bundled.__name__
            module = importlib.import_module(f"{package}.history_chronicle")
        except ImportError:
            continue
        classes.append(module.ChronicleProvider)
    return classes


@pytest.fixture(autouse=True)
def _no_history_provider_subprocess(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec: the full suite passes with no provider set up, and no provider code runs.

    Any attempt to run Chronicle fails the test — whether or not a real
    ``chronicle`` is on this machine's PATH — unless it is marked
    ``history_provider``. ``pytest.fail`` raises a BaseException, so Karni's
    "a provider failure is no brief" handling cannot swallow it. Global
    config and forced rule conditions are isolated from the developer's.
    """
    monkeypatch.delenv("KARNI_AGENT_CONDITIONS", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".xdg-config"))
    if request.node.get_closest_marker(HISTORY_MARKER) is not None:
        return
    real_run = subprocess.run

    def guarded(args: Any, *a: Any, **kw: Any) -> Any:
        if _spawns_chronicle(args):
            pytest.fail(f"a history provider spawned {args!r} without opting in")
        return real_run(args, *a, **kw)

    def no_run(self: Any, repo: Path, args: list[str], command: str) -> NoReturn:
        pytest.fail(f"the Chronicle provider tried to run `chronicle {' '.join(args)}`")

    monkeypatch.setattr(subprocess, "run", guarded)
    for cls in _chronicle_classes():
        monkeypatch.setattr(cls, "_run", no_run)
