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
* a small game to start from, the project's own code in ``frontend/src/game/``
  (the files of :data:`FILES`): its rules as plain functions (a seeded world,
  a run replayed from its seed and input log), the canvas on @karni/game's
  loop and input, the session with the server (the portal, the data client, a
  finished run reported as a score, progress, a save and analytics), and the
  page's hook and panels;
* a page at ``/game`` (``frontend/src/pages/game.tsx``) that hosts it inside the
  app: the calls go through the app's own API client, so a signed-in player's
  carry the account, and a guest keeps their progress by signing in with a
  code sent by email (``KARNI_EMAIL_OTP = True``);
* the game alone for the portals (``frontend/portal/``): ``npm run
  game:package`` builds, checks and zips one package per portal, calling the
  game API named by ``KARNI_GAME_API_URL`` across origins with the guest's
  token (``KARNI_GAME_CORS_ORIGINS`` on the server);
* ``karniGame({ relativeBase: false })`` from ``@karni/game/vite`` in
  ``frontend/vite.config.ts`` (the page's portal module, while the app keeps
  its own base) and its types in ``frontend/src/vite-env.d.ts``.

Only the project's own files are written: everything else is a dependency.

Override / escape hatch: every written file is the project's to change.
:data:`CLIENT_PACKAGE` names the client package in one place, and the files
are plain files in ``game_files/`` (``__GAME_SLUG__`` and ``__GAME_TITLE__``
are the game's).
"""

from __future__ import annotations

from importlib import resources

from karni_cli.generators.core import SETTINGS, Workspace
from karni_cli.project import CliError
from karni_cli.urls_edit import add_route

__all__ = ["CLIENT_PACKAGE", "FILES", "GAME_URLS", "plan"]

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
    "KARNI_PEOPLE = True\n"
    "# A guest keeps their progress by signing in with a code sent by email (no password).\n"
    "KARNI_EMAIL_OTP = True\n\n"
)
CALL = "karni_settings(globals())"
IMPORT = "from karni.conf import karni_settings\n"
CORS_IMPORT = "from corsheaders.defaults import default_headers\n"
CORS = (
    "\n\n# A portal build of the game calls /api/game/ from the portal's domain with a token.\n"
    "# KARNI_GAME_CORS_ORIGINS lists those origins, and the browser may send the header.\n"
    'KARNI_GAME_CORS_ORIGINS = env.list("KARNI_GAME_CORS_ORIGINS", default=[])  # noqa: F821\n'
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


@pytest.mark.django_db
def test_a_finished_run_counts_and_unlocks_the_first_achievement() -> None:
    load_content(Path(settings.BASE_DIR) / "content" / "game.yaml")
    client = APIClient()
    guest = client.post("/api/game/guest/", {{}}, format="json")
    client.credentials(HTTP_X_PLAYER_TOKEN=guest.data["token"])
    events = [
        {{"counter": "levels_done", "amount": 1}},
        {{"counter": "coins_collected", "amount": 3}},
    ]
    done = client.post(f"{{GAME}}progress/", {{"events": events}}, format="json")
    assert done.status_code == 200
    assert [row["key"] for row in done.data["unlocked"]] == ["first-run"]


@pytest.mark.django_db
def test_one_player_never_sees_another_players_save_or_wallet() -> None:
    load_content(Path(settings.BASE_DIR) / "content" / "game.yaml")
    first, second = APIClient(), APIClient()
    for client in (first, second):
        guest = client.post("/api/game/guest/", {{}}, format="json")
        client.credentials(HTTP_X_PLAYER_TOKEN=guest.data["token"])
    save = {{"data": {{"best": 900}}, "schema_version": 1, "base_version": 0}}
    assert first.put(f"{{GAME}}saves/main/", save, format="json").status_code == 200
    assert first.post(f"{{GAME}}daily/check-in/", {{}}, format="json").status_code == 200
    assert second.get(f"{{GAME}}saves/main/").status_code == 404
    coins = second.get(f"{{GAME}}wallet/").data["balances"]
    assert all(balance["balance"] == 0 for balance in coins)
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
          # trust: client lets any client claim it, so it stays low (per_day). With a portal
          # that confirms ads server to server, trust: callback (the default) is safer.
          - {{game: {slug}, key: ad-coins, title: Coins for an ad, kind: ad, amount: 25,
              trust: client, per_day: 3, cooldown: 60}}
          - game: {slug}
            key: first-run
            title: First run prize
            kind: achievement
            amount: 20
            achievements:
              - {{game: {slug}, key: first-run, title: First run, counter: levels_done, goal: 1}}
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

#: The game's own files, from ``game_files/``: the frontend's game, its page and its portal build.
FILES = (
    "frontend/src/game/rules.ts",
    "frontend/src/game/play.ts",
    "frontend/src/game/session.ts",
    "frontend/src/game/useGame.ts",
    "frontend/src/game/Hud.tsx",
    "frontend/src/pages/game.tsx",
    "frontend/portal/index.html",
    "frontend/portal/main.ts",
    "frontend/portal/style.css",
    "frontend/portal/vite.config.ts",
)
FRONTEND_PACKAGE = "frontend/package.json"
TSCONFIG = "frontend/tsconfig.json"
GITIGNORE = ".gitignore"
#: The portals that need no id of the project's: add --portal gamedistribution and
#: --portal y8 once their ids are in the build environment (karni-game portals).
PORTAL_SCRIPT = (
    "game:package",
    "karni-game package --root portal --portal web --portal itch --portal poki --portal crazygames",
)
PORTAL_IGNORE = (
    "# The portal packages of the game (npm run game:package).\nfrontend/portal/dist-portals/\n"
)


def game_file(rel: str, *, slug: str, title: str) -> str:
    """One of :data:`FILES`, with the game's slug and title in it."""
    text = resources.files("karni_cli.generators").joinpath("game_files", rel).read_text("utf-8")
    return text.replace("__GAME_SLUG__", slug).replace("__GAME_TITLE__", title)


VITE = "frontend/vite.config.ts"
VITE_IMPORT = 'import { karniGame } from "@karni/game/vite";\n'
#: The app keeps its own base (``/``, or ``--base`` of the image's build): a relative
#: base is for the portal packages, which frontend/portal/ builds.
VITE_GAME = "karniGame({ relativeBase: false })"
VITE_AFTER = 'import { karniTheme } from "@karni/ui/vite";\n'
VITE_PLUGINS = "plugins: [react(), tailwindcss(), karniTheme()]"
ENV_TYPES = "frontend/src/vite-env.d.ts"
GAME_TYPES = '/// <reference types="@karni/game/client" />\n'

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


def _vite(ws: Workspace) -> str:
    text = ws.read(VITE)
    if text is None or VITE_PLUGINS not in text or VITE_AFTER not in text:
        return f"Add karniGame() from @karni/game/vite to the plugins in {VITE} yourself."
    text = text.replace(VITE_AFTER, VITE_AFTER + VITE_IMPORT, 1)
    text = text.replace(
        VITE_PLUGINS, f"plugins: [react(), tailwindcss(), karniTheme(), {VITE_GAME}]", 1
    )
    ws.write(VITE, text)
    types = ws.read(ENV_TYPES)
    if types is not None and GAME_TYPES not in types:
        ws.write(ENV_TYPES, types + GAME_TYPES)
    return f"{VITE_GAME}: in {VITE} (the page's portal module), with its types in {ENV_TYPES}"


def _portal(ws: Workspace) -> str:
    """The portal build: its script, the folder in the type-check, its packages ignored."""
    import json

    text = ws.read(FRONTEND_PACKAGE)
    if text is not None:
        data = json.loads(text)
        data.setdefault("scripts", {}).setdefault(*PORTAL_SCRIPT)
        ws.write(FRONTEND_PACKAGE, json.dumps(data, indent=4) + "\n")
    config = ws.read(TSCONFIG)
    if config is not None and '"include": ["src"]' in config:
        ws.write(TSCONFIG, config.replace('"include": ["src"]', '"include": ["src", "portal"]', 1))
    ignore = ws.read(GITIGNORE)
    if ignore is not None and "dist-portals" not in ignore:
        ws.write(GITIGNORE, ignore.rstrip("\n") + "\n\n" + PORTAL_IGNORE)
    return (
        "frontend/portal/: the game alone for the portals (npm run game:package, "
        "KARNI_GAME_API_URL names the game API)"
    )


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
    if ws.exists(FRONTEND_PACKAGE):
        for rel in FILES:
            ws.create(rel, game_file(rel, slug=slug, title=title))
        lines.append(
            "frontend/src/game/: the game (its rules, canvas, session with the server and panels)"
        )
        lines.append(_route(ws))
        lines.append(_vite(ws))
        lines.append(_portal(ws))
    return lines
