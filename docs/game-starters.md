---
description: "Game starters: karni new --kind game --genre runner writes a complete small game, Sky Dash, on every layer of @karni/game and karni-game, with its tests; karni starters list --match ranks the starters for a one-line request; what a starter holds, the colour-safe palette, and how to add a starter of your own."
---

# Game starters

!!! warning "Experimental"
    Starters, `--genre` and `karni starters` are
    [experimental](stability.md#experimental-names): a name or a file may
    change in a minor release, with a CHANGELOG entry.

A starter is the game side's recipe: a small game you can play from the first
command, written as the project's own code on the framework, with its tests.
It holds only the game's own rules, scenes, drawing and content. The loop,
input, audio, scenes, the UI kit, drawing, collision, sound, the simulation
contract, saves, the portals and the server come from `@karni/game` and
`karni-game`, so a fix in them reaches every game made from a starter.

| Genre | The starter | What it shows |
|---|---|---|
| `runner` | One-tap runner, made as "Sky Dash": an endless track from a seed, a daily run with its own board, trails and hats bought with coins, an ad continue | the simulation and replay checks, scenes, the UI kit, drawing, collision, sound, save slots, the daily seed, boards, the wallet and shop, rewards and portal packages |
| `blank` | the small one-tap game `--kind game` writes on its own (the default) | the game's layout and its server side, to build on |

## One command to a playable game

```bash
pip install karni karni-cli karni-game
karni starters list --match "a one-tap runner with daily challenges and a cosmetics shop"
#   runner  18  One-tap runner: An endless runner: a seeded track, a daily run, a cosmetics shop and an ad continue
karni new "Sky Dash" --kind game --genre runner
cd sky_dash
```

`--genre` implies `--kind game`. The game is in `game/sky-dash/`, served by the
project at `/play/sky-dash/`, and its server side is in the project
([apps and games](apps-and-games.md)). Then, as `karni new` prints:

```bash
cp .env.example .env && docker compose up -d     # or a virtualenv, README.md says how
karni migrate && karni load content/game.yaml    # the game's boards, coins, rewards and items
(cd game/sky-dash && npm install && npm run dev) # http://localhost:5174/play/sky-dash/
```

What a player gets: a title with the bests, the coins and today's run; a run
that speeds up as it goes, with gaps, clouds to land on, spikes and coin arcs;
a pause menu with settings (volumes, mute, reduced motion, the colour-safe
palette, remapped keys); a game-over panel with the board; a shop of two
trails and two hats; coins once a day, for missions and achievements, and for
an ad; and one continue a run for an ad.

## What the runner holds

| Where | What |
|---|---|
| `game/<slug>/src/rules/` | the rules: a simulation of [`@karni/game/sim`](game-sim.md), pure and seeded. `world.ts` holds the numbers (speed, gravity, jumps), `track.ts` lays the track, `runner.ts` steps a run and moves the runner with [`@karni/game/collide`](game-collide.md) |
| `src/run.ts` | a run from start to end: the recorder, the endless and daily modes, the report to the server, the continue |
| `src/scenes/` | loading, title, play, pause, game over and shop on the [scene stack](game-scenes.md), with the [UI kit](game-ui.md)'s panels, dialog, settings, pause and touch buttons |
| `src/art/` | the drawing on [`@karni/game/draw`](game-draw.md): seven layers (sky, two parallax bands, the track, effects, clouds in front, the HUD), the runner, its hats and the coin painted in code and cut into sprites, particles, the trails |
| `src/sound.ts` | every sound, made by [`@karni/game/sfx`](game-sound.md): no audio files |
| `src/session.ts` | the server through the data client: the guest player, the save slots (`progress`, `daily`), the daily seed, the boards, the wallet, the shop, the rewards |
| `src/game.ts`, `src/palette.ts` | the game's names (boards, slots, rewards, items) and its palette |
| `tests/`, `scripts/smoke.mjs` | the rules' tests, determinism, a fuzz run and a replayed run, and the browser smoke run |
| `content/game.yaml` | the server's rows: the boards, the coins, the rewards, the items ([what a game declares](game.md#what-a-game-declares)) |
| `games/game.py`, `games/tests/` | the run check of both boards, and the server's tests |

## Trust, the server's side

The server decides every coin and price. The client reports what happened
and asks:

- **Scores.** Both boards require the run with every score: the seed and the
  inputs, with the run's own score, ticks and state hash in `meta`
  (`toRunRecord`). `games/game.py` rejects a score its run does not claim,
  flags a run that is not the simulation's, and flags a score a run of that
  length cannot reach at the top speed. Replaying the run on the server needs
  the TypeScript rules: the game's tests replay recorded runs with `verify`.
- **Today's run.** The daily board takes only a run on the server's seed of
  the day (`GET daily/`), so every player runs the same track. Offline, the
  game plays the device's seed for practice, and that run is not on the board.
- **Coins.** With a server, coins come only from the rewards
  `content/game.yaml` declares: the daily coins, achievements, missions and
  coins for an ad. The coins a run picks up count toward the collector
  achievement and the score. A build with no server keeps its own economy on
  the device, which never reaches a server.
- **The continue.** It is an ad reward worth no coins (`continue`, `trust:
  client`, three a day): the server records each claim and refuses a fourth one
  in a day, and the rules allow one continue a run. The continue is an input
  of the run, so a continued run still replays.
- **Players apart.** `games/tests/test_game.py` proves that one player never
  reads or changes another player's saves, scores or wallet.

## Its tests

| Command | What it runs |
|---|---|
| `npm test` (in `game/<slug>/`) | the rules: the track only has gaps a jump clears at the speed there, the jumps, the speed, a continue once; determinism (the same hash for the same seed and inputs), a fuzz run with random inputs and the rules' invariants, and a recorded run replayed to its score |
| `npm run check-rules` | no clock, `Math.random`, page or network in `src/rules/` |
| `npm run smoke` | a build for a portal with no server, played in headless Chromium by touch on a phone and by keys on a desktop, then booted with broken storage: no console error, page error or failed request, within a frame-time budget (95th percentile 40 ms). `npx playwright install chromium` once before |
| `karni test` | the server: a guest runs, every score needs its run, today's board, coins and the shop, the continue's cap, players kept apart |

The repository builds each starter from scratch and runs all of them
(`packages/karni-cli/tests/test_starter_builds.py`, CI's starters job).

## The colour-safe palette

Everything the player must tell apart (the runner, a coin, a spike, the
ground, a cloud to land on) differs in lightness and in shape, not only in
hue, and the hues come from the Okabe-Ito set, which stays apart for the
common kinds of colour blindness (`COLOUR_SAFE` of `@karni/game/ui`). The
colour-safe setting adds outlines to what the player touches and draws the
spikes in black and white. A game from the starter keeps that when it
changes the look: pick its colours from `COLOUR_SAFE`, keep a lightness step
between what must be told apart, and give a danger a shape of its own.

## Changing it

The starter's files are the project's own once written. What people change
first: the track's patterns (`src/rules/track.ts`), the runner's numbers
(`src/rules/world.ts`), the look and the sounds, and the items and prices (in
`content/game.yaml` and `src/game.ts`, which name the same keys). After a
change to the rules, run `npm test` and `npm run check-rules`. A golden run in
the tests changes its hash with the rules: that is the test working.

## A starter of your own

`karni starters list` reads the `karni.starters` entry points of the
environment. A package adds one with a folder:

```text
my_starters/puzzle/
  starter.toml   name, title, purpose, use_when, usually_changed, example
  game/          the game's files, written to game/<slug>/
  project/       the project's files at their paths (games/game.py, games/tests/, content/game.yaml)
```

```toml
# pyproject.toml of the package
[project.entry-points."karni.starters"]
puzzle = "my_starters:puzzle"   # a folder (an importlib.resources traversable)
```

`__GAME_SLUG__`, `__GAME_TITLE__` and `__KARNI_GAME_SPEC__` are filled in as
the files are written, and the files are text. `--match` scores a starter by
the words of its name, `use_when` and `purpose`, as `karni recipes list
--match` scores recipes. A genre that is not there is
[C480](errors.md#c480), `--genre` with another kind is
[C481](errors.md#c481), and a starter that cannot be read is
[C482](errors.md#c482).
