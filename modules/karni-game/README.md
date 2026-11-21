# karni-game

Games for Karni: guest players, cloud saves, leaderboards, a soft-currency wallet, daily content and achievements, with a realtime server contract.

[![PyPI](https://img.shields.io/pypi/v/karni-game)](https://pypi.org/project/karni-game/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/game/)

The server side of a game, for any game a project hosts. The server decides every reward, every price and every balance: a client only reports and asks. It is **experimental**: its names may change in a minor release, with a CHANGELOG entry.

The guide is [docs/game.md](https://cbsshekhawat18-lab.github.io/karni/game/), and the HTTP contract a client, a realtime server and a portal code against is [docs/game-api.md](https://cbsshekhawat18-lab.github.io/karni/game-api/).

## Install

```bash
pip install karni-game              # karni-game[commerce] for real-money items
karni add game
```

A player is a person of the people contract, so set it above the settings call, and mount the API once:

```python
# config/settings.py
KARNI_PEOPLE = True

# config/urls.py, before path("api/", include("karni.api.urls"))
path("api/game/", include("karni_game.urls")),
```

Then `make migrate`. `karni new "Block Hopper" --kind game` writes all of it, with a `games` app, the game declared in `content/game.yaml`, and the game itself in `game/block-hopper/`, served at `/play/block-hopper/`. `--kind app+game` puts the game on a page of an app instead, at `/game`.

## What it adds

| Part | What |
|---|---|
| Players | `Player` on `people.Person`: a guest with a token the server issues, an account once its email is verified, an upgrade that keeps the guest's progress (`people.merge` with the module's merge hook). |
| Saves | `Save`: versioned JSON per player, game and slot, a server version counter (409 with the server's copy on a stale write), a size limit, save migrations per game. |
| Boards | `Board`, `Score`, `Best`: periods on the game's clock, plausible ranges, runs (seed and input log) kept for review, flagged runs, run checks. |
| Wallet | `Currency`, `Wallet`, `LedgerEntry`: atomic and capped, a ledger entry with a reason for every move. |
| Rewards and shop | `Reward`, `Claim`, `Item`, `Ownership`: rewards declared on the server (daily, ad with a signed portal callback, mission, achievement, match, staff), cosmetics owned and equipped, a shop in soft currency, real-money items as the karni-commerce kind `game_item`. |
| Daily | `Streak`: the server's date, a daily seed per game, streaks with a grace rule, a daily board. |
| Achievements | `Achievement`, `Mission`, `Progress`, `Unlock`, `Completion`: counters the game reports, unlocked and granted by the server. |
| Config | `ConfigValue`: remote config and feature flags with a rollout, in the one boot call. Analytics checked against the game's schema and published as `game.analytics.tracked`. |
| Multiplayer | `Match`: a short-lived HS256 player token for a realtime server of your own, and its signed results report. |

The admin ships explicit classes (`karni_game/admin.py`) for players, scores, wallets and the ledger, where staff act. The other models use the derived admin. Two roles come with it (`game-manager`, `game-moderator`, the `karni.roles` entry point).

## Settings

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `KARNI_GAME_RATES` | | the defaults of docs/game-api.md | rates of the limited writes, by scope (`None` turns one off) |
| `KARNI_GAME_TOKEN_HEADER` | `KARNI_GAME_TOKEN_HEADER` | `X-Player-Token` | the guest token's header |
| `KARNI_GAME_CORS_ORIGINS` | `KARNI_GAME_CORS_ORIGINS` | `[]` | origins a portal build calls `/api/game/` from (tokens only) |
| `KARNI_GAME_SERVER_SECRET` | `KARNI_GAME_SERVER_SECRET` | blank | the realtime server's shared secret (at least 32 bytes). Blank: no multiplayer |
| `KARNI_GAME_TOKEN_ISSUER` | `KARNI_GAME_TOKEN_ISSUER` | `karni-game` | the player token's `iss` |
| `KARNI_GAME_TOKEN_SECONDS` | `KARNI_GAME_TOKEN_SECONDS` | `300` | the player token's life |
| `KARNI_GAME_PORTALS` | | `{}` | portals that call back after an ad: `{name: {"secret", "verifier"}}` |
| `KARNI_GAME_SIGNATURE_TOLERANCE` | `KARNI_GAME_SIGNATURE_TOLERANCE` | `300` | seconds a signed request's timestamp may be off |
| `KARNI_GAME_AD_INTENT_SECONDS` | `KARNI_GAME_AD_INTENT_SECONDS` | `3600` | an ad reward intent's life |
| `KARNI_GAME_CLIENT_CLAIMS_PER_DAY` | `KARNI_GAME_CLIENT_CLAIMS_PER_DAY` | `5` | the cap of a client-claimed ad reward |
| `KARNI_GAME_INTENT_DAYS` | `KARNI_GAME_INTENT_DAYS` | `7` | days a retry key is kept |
| `KARNI_GAME_MAX_SAVE_BYTES` | `KARNI_GAME_MAX_SAVE_BYTES` | `1048576` | the largest save any game allows |
| `KARNI_GAME_MAX_RUN_BYTES` | `KARNI_GAME_MAX_RUN_BYTES` | `262144` | the largest run record |
| `KARNI_GAME_MERGER` | `KARNI_GAME_MERGER` | `karni_game.merge.Merger` | the merge rules of two players |
| `KARNI_GAME_DAILY_SEED` | `KARNI_GAME_DAILY_SEED` | `karni_game.daily.daily_seed` | `seed(game, day) -> int` |
| `KARNI_GAME_AUTODISCOVER` | `KARNI_GAME_AUTODISCOVER` | `True` | import each app's `game.py` |
| `KARNI_GAME_ROLES` | `KARNI_GAME_ROLES` | `True` | declare the two roles |

## Security

- A player is found from the request only (the account, else the guest token). No endpoint takes a player's id from a client.
- A guest token is stored as its SHA-256 and revoked on upgrade.
- Balances change only through `karni_game.wallet.change` (row lock, conditional update, never below 0, capped).
- Portal callbacks and realtime reports are HMAC-SHA256 signed over a timestamp and the raw body, and refused past `KARNI_GAME_SIGNATURE_TOLERANCE`.
- Writes are rate limited per player, and a retry with the same `intent` never counts twice.

## Escape hatches

`KARNI_GAME_MERGER`, `KARNI_GAME_DAILY_SEED`, a run check and a save migration per game in `<app>/game.py`, a verifier per portal, the views of `karni_game.api` (subclass and mount your own), and the service modules the views call. The guide lists each.

## Tests

```bash
cd modules/karni-game && python -m pytest
# the wallet under two requests at once, on PostgreSQL:
PYTHONPATH=../../.github/ci DATABASE_URL=postgres://... python -m pytest --ds=karni_postgres_settings tests/test_concurrency.py
```
