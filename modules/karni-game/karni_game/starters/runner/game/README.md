# __GAME_TITLE__

A one-tap endless runner: tap (or Space, or the up arrow) to jump, and again in the air to jump
twice. The track is laid from a seed, so the same seed is the same track for everyone: today's
run is the server's seed of the day, with a board of its own. Coins buy trails and hats in the
shop, and a rewarded ad buys one continue a run.

It started from Karni's runner starter (`karni new --kind game --genre runner`). Every file here
is the project's own. Everything else comes from `@karni/game`: the loop, input, audio, scenes,
the UI kit, drawing, collision, sound, the simulation contract, saves, portals and the data
client.

| Where | What |
|---|---|
| `src/rules/` | the rules: a simulation of `@karni/game/sim`, pure, seeded and replayable |
| `src/run.ts` | a run from start to end: the recorder, the modes, the continue |
| `src/scenes/` | loading, title, play, pause, game over and shop on the scene stack |
| `src/art/` | the drawing on `@karni/game/draw`: layers, parallax, sprites painted in code, particles, trails |
| `src/sound.ts` | every sound, made by `@karni/game/sfx` (no audio files) |
| `src/session.ts` | the server: the player, the save slots, the daily seed, the boards, the wallet, the shop |
| `src/game.ts`, `src/palette.ts` | the game's names (boards, rewards, items) and its colour-safe palette |
| `tests/` | the rules' tests, determinism, a fuzz run and a replayed run |

The server side is in the project: `content/game.yaml` declares the boards, coins, rewards and
items (`karni load content/game.yaml`), `games/game.py` checks every run sent with a score, and
`games/tests/` proves that one player never reaches another's saves, scores or wallet.

```sh
npm install
npm run dev          # http://localhost:5174/play/__GAME_SLUG__/, the game API proxied to Django
npm test             # the rules, determinism, fuzz and a replayed run
npm run check-rules  # no clock, Math.random, page or network in src/rules/
npx playwright install chromium && npm run smoke   # played in a headless browser
npm run build        # dist/, which the project serves at /play/__GAME_SLUG__/
npm run package      # one package per game portal, checked and zipped
```

The lock file is made by the first `npm install`: commit it.
