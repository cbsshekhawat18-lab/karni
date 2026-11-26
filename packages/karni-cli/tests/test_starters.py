"""Game starters: karni starters list and show, karni new --genre.

The starters are the blank start built into karni-cli and the karni.starters
entry points (karni-game ships the runner). These tests write projects and read
their files. tests/test_starter_builds.py (-m starters) runs a written game's
own checks: npm, its tests, a browser.
"""

from __future__ import annotations

import json
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import starters
from karni_cli.main import app

from .conftest import TEMPLATE, require_modules

REQUEST = "a one-tap runner with daily challenges and a cosmetics shop"


def _cli(*args: str):
    return CliRunner().invoke(app, list(args))


def _error(result) -> str:
    """A CliError the command ended with: its code, then its message."""
    exc = result.exception
    return f"{getattr(exc, 'code', '')}: {exc}" if exc is not None else result.output


def _runner() -> starters.Starter:
    require_modules("karni-game")
    return starters.load().require("runner")


def test_the_starters_are_the_blank_start_and_the_runner_from_karni_game() -> None:
    _runner()
    listed = _cli("starters", "list")
    assert listed.exit_code == 0, listed.output
    assert "runner  One-tap runner:" in listed.output
    assert "blank " in listed.output and "the default" in listed.output
    data = json.loads(_cli("starters", "list", "--json").output)
    assert [entry["name"] for entry in data["starters"]] == ["runner"]
    assert data["blank"]["name"] == "blank" and data["missing"] == []


def test_match_ranks_the_runner_first_for_a_runner_request_and_nothing_for_a_shop() -> None:
    _runner()
    data = json.loads(_cli("starters", "list", "--match", REQUEST, "--json").output)
    assert data["starters"][0]["name"] == "runner"
    assert {"runner", "daily", "shop"} <= set(data["starters"][0]["matched"])
    other = json.loads(
        _cli("starters", "list", "--match", "invoices for a law firm", "--json").output
    )
    assert other["starters"] == []


def test_show_lists_the_files_a_starter_writes() -> None:
    _runner()
    shown = json.loads(_cli("starters", "show", "runner", "--json").output)
    game = set(shown["files"]["game"])
    assert {"package.json", "src/main.ts", "src/rules/runner.ts", "tests/sim.test.ts"} <= game
    assert {"src/scenes/shop.ts", "src/scenes/over.ts", "scripts/smoke.mjs"} <= game
    assert set(shown["files"]["project"]) == {
        "content/game.yaml",
        "games/game.py",
        "games/tests/test_game.py",
    }
    assert shown["new"] == 'karni new "Sky Dash" --kind game --genre runner'


def test_an_unknown_genre_is_a_coded_error_naming_the_genres() -> None:
    result = _cli("starters", "show", "puzzle")
    assert result.exit_code == 1
    assert "C480" in _error(result) and "blank" in _error(result)


def test_a_known_genre_whose_package_is_missing_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(starters, "_entry_points", list)
    with pytest.raises(Exception, match=r"C480|runner comes with karni-game") as found:
        starters.load().require("runner")
    assert "pip install karni-game" in str(found.value)


def test_a_starter_that_cannot_be_read_is_left_out_and_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "broken").mkdir()
    point = EntryPoint(name="broken", value="broken", group=starters.ENTRY_POINT_GROUP)
    monkeypatch.setattr(starters, "_entry_points", lambda: [point])
    monkeypatch.setattr(starters, "_folder_of", lambda _point: tmp_path / "broken")
    loaded = starters.load()
    assert loaded.names() == ["blank"]
    assert loaded.problems and "C482" in loaded.problems[0] and "starter.toml" in loaded.problems[0]


def _new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str):
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    return CliRunner().invoke(app, ["new", *args, "-o", str(tmp_path), "--no-git"])


def test_new_with_genre_runner_writes_the_starter_as_the_projects_own_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    result = _new(tmp_path, monkeypatch, "Sky Dash", "--genre", "runner")
    assert result.exit_code == 0, result.output
    project = tmp_path / "sky_dash"
    assert 'kind = "game"' in (project / "pyproject.toml").read_text()  # --genre is a game first
    game = project / "game" / "sky-dash"
    written = runner.render(starters.GAME_DIR, slug="sky-dash", title="Sky Dash", spec="^0.7.0")
    for rel, text in written.items():
        assert (game / rel).read_text() == text, rel
    package = json.loads((game / "package.json").read_text())
    assert package["name"] == "sky-dash" and package["dependencies"] == {"@karni/game": "^0.7.0"}
    assert "author" not in package
    assert 'export const GAME = "sky-dash";' in (game / "src" / "game.ts").read_text()
    # The server side is the starter's: its boards, its run check, its tests.
    assert "key: daily, title: Today's run" in (project / "content" / "game.yaml").read_text()
    assert "def plausible(" in (project / "games" / "game.py").read_text()
    assert "never_reads_or_changes" in (project / "games" / "tests" / "test_game.py").read_text()
    for path in game.rglob("*"):
        if path.is_file():
            text = path.read_text()
            for placeholder in ("__GAME_SLUG__", "__GAME_TITLE__", "__KARNI_GAME_SPEC__"):
                assert placeholder not in text, (path, placeholder)
    # The framework is not copied: the game imports it.
    main = (game / "src" / "main.ts").read_text()
    assert 'from "@karni/game/scenes"' in main and 'from "@karni/game/ui"' in main
    assert "npm run smoke" in result.output and "docs/game-starters.md" in result.output


def test_new_with_genre_blank_is_the_game_kind_game_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_modules("karni-game")
    blank = _new(tmp_path / "a", monkeypatch, "Block Hopper", "--kind", "game", "--genre", "blank")
    plain = _new(tmp_path / "b", monkeypatch, "Block Hopper", "--kind", "game")
    assert blank.exit_code == 0 and plain.exit_code == 0, blank.output + plain.output
    for rel in ("game/block-hopper/src/play.ts", "games/game.py", "content/game.yaml"):
        a = (tmp_path / "a" / "block_hopper" / rel).read_text()
        assert a == (tmp_path / "b" / "block_hopper" / rel).read_text(), rel


@pytest.mark.parametrize(
    ("args", "clash"),
    [
        (["--kind", "app", "--genre", "runner"], "--kind app is not a game first"),
        (["--kind", "app+game", "--genre", "runner"], "--kind app+game is not a game first"),
        (["--recipe", "shop", "--genre", "runner"], "--recipe"),
    ],
)
def test_genre_goes_with_the_game_kind_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], clash: str
) -> None:
    result = _new(tmp_path, monkeypatch, "Mixed Up", *args)
    assert result.exit_code == 1
    assert "C481" in _error(result) and clash in _error(result)
    assert not (tmp_path / "mixed_up").exists()  # checked before anything is written


def test_new_with_an_unknown_genre_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _new(tmp_path, monkeypatch, "Tile Match", "--kind", "game", "--genre", "puzzle")
    assert result.exit_code == 1 and "C480" in _error(result)
    assert not (tmp_path / "tile_match").exists()
