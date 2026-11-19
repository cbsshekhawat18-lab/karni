"""Experimental. ``karni new --kind game``: a project with a game in it, on the karni-game module.

What it adds to a new app project:

* the karni-game module, as ``karni add game`` wires it: the dependency, the
  app, and the client package ``@karni/game`` in ``frontend/package.json``;
* ``KARNI_PEOPLE = True`` (a player is the game profile of a person) and the
  game API's include in ``config/urls.py``;
* a ``games`` app: ``games/game.py`` for the game's server hooks (save
  migrations, run checks) and a test that a guest plays;
* ``content/game.yaml``: the game declared on the server (its boards, its
  currency, rewards, an item, an achievement, a mission and config), loaded
  with ``karni load content/game.yaml``;
* a page at ``/game`` (``frontend/src/pages/game.tsx``) that hosts the game,
  and ``frontend/src/game/`` where the game's own code goes.

Only the project's own files are written: everything else is a dependency.

Override / escape hatch: every written file is the project's to change.
:data:`CLIENT_PACKAGE` names the client package in one place.
"""

from __future__ import annotations

from karni_cli.generators.core import SETTINGS, Workspace
from karni_cli.project import CliError
from karni_cli.urls_edit import add_route

__all__ = ["CLIENT_PACKAGE", "GAME_URLS", "plan"]

#: The game's client package (``modules/karni-game/ui``): what the game page imports.
CLIENT_PACKAGE = "@karni/game"
#: The game API's include, at the ``# karni:urls`` marker.
GAME_URLS = 'path("api/game/", include("karni_game.urls")),'
URLS = "config/urls.py"
ROUTES = "frontend/src/routes.tsx"
IMPORT_MARKER = "// karni:page-imports"
ROUTE_MARKER = "// karni:routes"
PEOPLE = (
    "# A player is the game profile of a person: karni-game needs the people contract.\n"
    "KARNI_PEOPLE = True\n\n"
)
CALL = "karni_settings(globals())"
IMPORT = "from karni.conf import karni_settings\n"
CORS_IMPORT = "from corsheaders.defaults import default_headers\n"
CORS = (
    "\n\n# A portal build of the game calls /api/game/ from the portal's domain with a token\n"
    "# (KARNI_GAME_CORS_ORIGINS lists those origins): the browser may send its header.\n"
    'CORS_ALLOW_HEADERS = (*default_headers, "x-player-token")'
)

HOOKS = '''"""The game's server hooks: save migrations and run checks (karni_game.hooks).

karni-game imports this module at startup. Register a step for each new shape
of the save, and raise save_schema_version in content/game.yaml with it:

    @hooks.save_migration("{slug}", 1)
    def levels_become_a_list(data):
        return {{**data, "levels": list(range(1, data.pop("level", 0) + 1))}}

A run check sees a score with its run (seed and input log) before it counts,
and answers "accept", "flag" (held for staff) or "reject":

    @hooks.run_check("{slug}", "high")
    def replay(score, run):
        return "accept"
"""

from karni_game import hooks  # noqa: F401
'''

TEST = '''"""The game is declared on the server, and a guest plays it."""

from pathlib import Path

import pytest
from django.conf import settings
from karni.transfer.loading import load_content
from rest_framework.test import APIClient

GAME = "/api/game/{slug}/"


@pytest.mark.django_db
def test_a_guest_plays_the_game() -> None:
    load_content(Path(settings.BASE_DIR) / "content" / "game.yaml")
    client = APIClient()
    guest = client.post("/api/game/guest/", {{}}, format="json")
    assert guest.status_code == 201
    client.credentials(HTTP_X_PLAYER_TOKEN=guest.data["token"])
    assert client.get(GAME).data["game"]["slug"] == "{slug}"
    save = {{"data": {{"level": 1}}, "schema_version": 1, "base_version": 0}}
    assert client.put(f"{{GAME}}saves/main/", save, format="json").status_code == 200
    score = client.post(f"{{GAME}}boards/high/scores/", {{"value": 120}}, format="json")
    assert score.status_code == 201
    assert client.get(f"{{GAME}}boards/high/").data["entries"][0]["value"] == 120
'''

CONTENT = """# {title}, declared on the server: karni load content/game.yaml (again after a change).
# The server decides every reward and price from here: the client only reports and asks.
# docs/game.md says what each row means.
karni_game.Game:
  - slug: {slug}
    title: {title}
    settings:
      timezone: UTC
      save_schema_version: 1
      max_slots: 3
      analytics:
        level_started: {{level: int}}
        level_done: {{level: int, ms: int}}
    boards:
      - {{key: high, title: High score, order: desc, periods: [all, daily, weekly],
          min_value: 0, max_value: 1000000}}
      - {{key: daily, title: Daily run, order: desc, periods: [daily], daily_seed: true,
          min_value: 0, max_value: 1000000}}
    currencies:
      - key: coins
        title: Coins
        cap: 99999
        rewards:
          - {{game: {slug}, key: daily-coins, title: Daily coins, kind: daily, amount: 10}}
          - {{game: {slug}, key: ad-coins, title: Coins for an ad, kind: ad, amount: 25,
              per_day: 5, cooldown: 60}}
          - game: {slug}
            key: collector
            title: Collector's prize
            kind: achievement
            amount: 50
            achievements:
              - {{game: {slug}, key: collector, title: Collector, counter: coins_collected,
                  goal: 300}}
          - game: {slug}
            key: three-levels
            title: Three levels a day
            kind: mission
            amount: 30
            missions:
              - {{game: {slug}, key: three-levels, title: Three levels today,
                  counter: levels_done, goal: 3, period: daily}}
        items:
          - {{game: {slug}, key: red-cap, title: Red cap, slot: hat, price: 50}}
    config:
      - {{key: start_level, value: 1}}
      - {{key: new_levels, flag: true, value: false}}
"""

GAME_SHELL = """// The game itself. Keep its rules in pure functions (tested without a browser)
// and its drawing here. @karni/game has the loop, input, audio, local saves, the
// portal adapter and the data client: docs/game.md.

export interface Running {
    stop(): void;
}

export function startGame(canvas: HTMLCanvasElement, title: string): Running {
    const context = canvas.getContext("2d");
    let frame = 0;
    const draw = (): void => {
        if (context !== null) {
            context.fillStyle = "#101820";
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = "#f2f2f2";
            context.font = "20px sans-serif";
            context.fillText(title, 24, 48);
        }
        frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return { stop: () => cancelAnimationFrame(frame) };
}
"""

PAGE = """// The page that hosts the game: the canvas, the player, the data client. The game's
// code is in ../game. Guests play without an account and keep their progress when
// they sign in (docs/game.md).
import {{ createGameClient, createStorage }} from "{package}";
import {{ useEffect, useRef, useState }} from "react";
import {{ startGame }} from "../game";

const GAME = "{slug}";

export default function GamePage() {{
    const canvas = useRef<HTMLCanvasElement | null>(null);
    const [ready, setReady] = useState(false);

    useEffect(() => {{
        const element = canvas.current;
        if (element === null) {{
            return undefined;
        }}
        const storage = createStorage({{ namespace: GAME }});
        const client = createGameClient({{ game: GAME, storage, server: {{}} }});
        const running = startGame(element, "{title}");
        let live = true;
        void client
            .boot()
            .then(() => client.signInGuest())
            .then(() => {{
                if (live) {{
                    setReady(true);
                }}
            }});
        return () => {{
            live = false;
            running.stop();
        }};
    }}, []);

    return (
        <main className="mx-auto max-w-3xl p-4">
            <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
            <canvas ref={{canvas}} width={{960}} height={{540}} className="w-full rounded" />
            <p className="mt-2 text-sm">{{ready ? "Playing." : "Loading."}}</p>
        </main>
    );
}}
"""

ROUTE = (
    'createRoute({ getParentRoute: () => root, path: "/game", component: GamePage, '
    "staticData: { public: true } }),"
)


def _settings(ws: Workspace) -> str:
    text = ws.read(SETTINGS)
    if text is None or CALL not in text:
        raise CliError(f"{SETTINGS.as_posix()} with {CALL} was not found.", code="C001")
    if "KARNI_PEOPLE" in text:
        return "KARNI_PEOPLE: already in config/settings.py"
    text = text.replace(CALL, PEOPLE + CALL + CORS, 1)
    if IMPORT in text and CORS_IMPORT not in text:
        text = text.replace(IMPORT, CORS_IMPORT + IMPORT, 1)
    ws.write(SETTINGS, text)
    return (
        "KARNI_PEOPLE = True (a player is a person) and the guest token's CORS header: in "
        "config/settings.py"
    )


def _urls(ws: Workspace) -> str:
    text = ws.read(URLS)
    if text is None:
        raise CliError(f"{URLS} not found.", code="C001")
    wired = add_route(text, GAME_URLS, filename=URLS, manual=f"Add {GAME_URLS} to {URLS}.")
    if wired is None:
        return f"{GAME_URLS}: already in {URLS}"
    ws.write(URLS, wired)
    return f"{GAME_URLS}: in {URLS} (the game API at /api/game/)"


def _route(ws: Workspace) -> str:
    text = ws.read(ROUTES)
    if text is None or IMPORT_MARKER not in text or ROUTE_MARKER not in text:
        return f"Register the game page in {ROUTES} yourself: {ROUTE}"
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if IMPORT_MARKER in line)
    lines.insert(index, 'import GamePage from "./pages/game";')
    index = next(i for i, line in enumerate(lines) if ROUTE_MARKER in line)
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines.insert(index, indent + ROUTE)
    ws.write(ROUTES, "\n".join(lines) + "\n")
    return f"/game: the page that hosts the game, in {ROUTES}"


def plan(ws: Workspace, *, title: str, slug: str) -> list[str]:
    """Plan the game kind's files into ``ws`` (a new app project); returns what it did."""
    from karni_cli.commands.add import plan_module
    from karni_cli.generators import app

    lines = plan_module(ws, "game")
    lines.append(_settings(ws))
    lines.append(_urls(ws))
    app.plan(ws, "games", next_step=False)
    ws.create("games/game.py", HOOKS.format(slug=slug))
    ws.create("games/tests/test_game.py", TEST.format(slug=slug))
    ws.create("content/game.yaml", CONTENT.format(slug=slug, title=title))
    lines.append("games: the game's server hooks (games/game.py) and its test")
    lines.append("content/game.yaml: the game, its boards, currency, rewards and config")
    if ws.exists("frontend/package.json"):
        ws.create("frontend/src/game/index.ts", GAME_SHELL)
        ws.create(
            "frontend/src/pages/game.tsx",
            PAGE.format(slug=slug, title=title, package=CLIENT_PACKAGE),
        )
        lines.append(_route(ws))
    return lines
