"""Each game starter built from scratch (experimental): karni new --genre, every check real.

``pytest -m starters`` runs these, and CI's starters job runs them, so a starter
never rots. The test writes ``karni new "<Name>" --kind game --genre <genre>``,
then runs what its developer runs: the server's migrations, ``karni check`` and
its tests on SQLite, then in ``game/<slug>/`` an install of this checkout's
``@karni/game`` (the tarball ``npm pack`` wrote, named by ``KARNI_GAME_TARBALL``),
the type check, the rules' tests, the purity check, the build and the smoke run
in headless Chromium within its frame budget.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli.main import app

from .conftest import TEMPLATE, require_modules
from .test_kinds import _run
from .test_make_gate import _karni_importable, _project_interpreter

pytestmark = pytest.mark.starters

#: The genres built here, with the name of the game each one is made as.
GENRES = {"runner": "Sky Dash"}


def _npm(folder: Path, *args: str, timeout: int = 900) -> str:
    started = time.monotonic()
    proc = subprocess.run(
        ["npm", *args], cwd=folder, text=True, capture_output=True, check=False, timeout=timeout
    )
    took = time.monotonic() - started
    print(f"npm {' '.join(args)}: {took:.1f}s")
    assert proc.returncode == 0, (
        f"npm {' '.join(args)}:\n{proc.stdout[-4000:]}{proc.stderr[-4000:]}"
    )
    return proc.stdout


@pytest.mark.skipif(not _karni_importable(), reason="needs karni + Django in this interpreter")
@pytest.mark.parametrize("genre", sorted(GENRES))
def test_a_starter_builds_from_scratch_with_every_check_green(
    genre: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_modules("karni-game")
    tarball = os.environ.get("KARNI_GAME_TARBALL", "")
    if not tarball or not Path(tarball).is_file() or shutil.which("npm") is None:
        pytest.skip(
            "needs npm and KARNI_GAME_TARBALL: (cd modules/karni-game/ui && npm ci && npm run "
            "build && npm pack), then KARNI_GAME_TARBALL=<the .tgz>"
        )
    name = GENRES[genre]
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(
        app, ["new", name, "--kind", "game", "--genre", genre, "-o", str(tmp_path), "--no-git"]
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception!r}"
    project = tmp_path / name.lower().replace(" ", "_")
    game = project / "game" / name.lower().replace(" ", "-")

    # The server: its migrations, karni check and its tests (the boards, the shop, the
    # continue, and one player never reaching another's saves, scores or wallet).
    monkeypatch.chdir(project)
    python = _project_interpreter(project, tmp_path, monkeypatch)
    for args in (
        ("manage.py", "migrate", "-v", "0"),
        ("manage.py", "karni_check"),
        ("-m", "pytest", "-q", "-p", "no:cacheprovider"),
    ):
        proc = _run(project, python, *args)
        assert proc.returncode == 0, f"{args}:\n{proc.stdout[-4000:]}{proc.stderr[-4000:]}"

    # The game: this checkout's @karni/game, then everything its README says to run.
    _npm(game, "install", "--no-audit", "--no-fund", tarball)
    _npm(game, "run", "typecheck")
    tests = _npm(game, "test")
    assert " passed" in tests and "failed" not in tests
    assert "the rules are pure" in _npm(game, "run", "check-rules")
    _npm(game, "run", "build")
    assert (game / "dist" / "index.html").is_file()
    if os.environ.get("KARNI_STARTER_SMOKE", "1") != "0":
        # The Chromium of the Playwright the game installed (nothing to do when it is there).
        proc = subprocess.run(
            ["npx", "playwright", "install", "chromium"],
            cwd=game,
            text=True,
            capture_output=True,
            check=False,
            timeout=900,
        )
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
        smoke = _npm(game, "run", "smoke")
        assert smoke.count("ok   ") == 2, smoke
        print(smoke.strip())
