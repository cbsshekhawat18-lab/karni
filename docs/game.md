---
description: "karni-game (experimental): the server side of a game. Guest players with a token the server issues, who keep their progress when they sign in, versioned cloud saves with a conflict rule, leaderboards with plausible ranges and flagged runs, a soft-currency wallet with a ledger, rewards and a shop, daily content on the server's date, achievements and missions, remote config and flags, analytics through the family events, the admin, and a contract for a realtime server of your own."
---

# Games (karni-game)

!!! warning "Experimental"
    The karni-game module, its HTTP contract ([the game API](game-api.md)) and
    the game kinds of `karni new` are [experimental](stability.md#experimental-names):
    their names may change in a minor release, with a CHANGELOG entry. The
    error codes keep their meaning.

A browser game keeps its progress in the browser until it needs more: a save
on every device, a board shared by every player, coins nobody can edit, a
daily level that is the same for everyone. karni-game is that server side,
once, for any game a project hosts. The game's own code stays in the browser
([the `@karni/game` client](game-client.md) helps there). The server decides every reward, every
price and every balance: a client only reports what happened and asks.

```bash
pip install karni-game
karni add game
```

```python
# config/settings.py, above karni_settings(globals())
KARNI_PEOPLE = True

# config/urls.py
path("api/game/", include("karni_game.urls")),
```

Then `make migrate`. A player is a [person](people.md), so the people
contract is needed (`karni.GAME001` until `KARNI_PEOPLE` is set). `karni
check` reports `GAME030` while the include is missing.

`karni new "Block Hopper" --kind game` makes a project with all of that
written, a `games` app, the game declared in `content/game.yaml`, and the game
itself in `game/block-hopper/`, served at `/play/block-hopper/`. `--kind
app+game` puts the game on a page of an app instead ([below](#a-new-game-project),
and [apps and games](apps-and-games.md)).

## What a game declares

A **game** is a row: its slug (in every path of the API), its title, and its
settings. What it declares are rows too, found by the game and a `key`:

| Row | What it is |
|---|---|
| `Game` | `slug`, `title`, `is_active`, `settings` (below) |
| `Board` | a leaderboard: `order` (`desc` higher is better, `asc` lower, for a time), `periods` (`all`, `daily`, `weekly`), `min_value` and `max_value` (the plausible range), `review_beyond`, `requires_run`, `keep_runs`, `daily_seed` |
| `Currency` | a soft currency: `key`, `title`, `cap` (the most a wallet holds) |
| `Reward` | `kind` (`daily`, `ad`, `mission`, `achievement`, `match`, `grant`), `currency`, `amount`, `per_day`, `cooldown` (seconds), `trust` (an ad reward: `callback`, the default, or `client`) |
| `Item` | a cosmetic: `slot` (hat, skin), `currency` and `price` for the shop, or `real_money` and `money_price` for the cart |
| `Achievement` | a `counter`, a `goal`, `hidden`, an optional `reward` |
| `Mission` | a `counter`, a `goal`, a `period` (`once`, `daily`, `weekly`), an optional `reward` |
| `ConfigValue` | a remote config value (any JSON), or a feature flag (`flag`, `value`, `rollout` in percent) |

Staff edit them in the admin. A project keeps them in a content file and
loads it in every environment with [`karni load`](content-loading.md), which
creates or updates rows by their keys and changes nothing the second time:

```yaml
# content/game.yaml: karni load content/game.yaml
karni_game.Game:
  - slug: block-hopper
    title: Block Hopper
    settings: {save_schema_version: 1, analytics: {level_done: {level: int, ms: int}}}
    boards:
      - {key: high, title: High score, periods: [all, daily, weekly], min_value: 0, max_value: 1000000}
    currencies:
      - key: coins
        title: Coins
        cap: 99999
        rewards:
          - {game: block-hopper, key: daily-coins, title: Daily coins, kind: daily, amount: 10}
          - game: block-hopper
            key: collector
            title: Collector's prize
            kind: achievement
            amount: 50
            achievements:
              - {game: block-hopper, key: collector, title: Collector, counter: coins_collected, goal: 300}
        items:
          - {game: block-hopper, key: red-cap, title: Red cap, slot: hat, price: 50}
    config:
      - {key: jump_height, value: 3.5}
      - {key: night_mode, flag: true, value: false, rollout: 20}
```

A reward and an item sit under their currency, and an achievement or a
mission under its reward, so each finds the right one. They name their game
too, and a row whose currency or reward is of another game is refused.

### Game settings

`Game.settings` is JSON checked by `karni_game.gamesettings.GameSettings`
(`GAME026` for a value it refuses). Every field has a default:

| Field | Default | What |
|---|---|---|
| `timezone` | `UTC` | The game's clock: its day starts at midnight there. |
| `save_schema_version` | `1` | The shape of the save data the game writes now. |
| `max_save_bytes` | `65536` | The largest save (at most `KARNI_GAME_MAX_SAVE_BYTES`). |
| `max_slots` | `5` | Save slots per player. |
| `streak_grace_days` | `1` | Days a player may miss and keep the daily streak. |
| `max_progress_step` | `1000` | The largest amount one progress event adds to a counter. |
| `analytics` | `{}` | The analytics events the game may send: `{name: {prop: type}}`, a type of `int`, `float`, `str` or `bool`. |

## Players: a guest first, an account later

A player is the game profile of a person (`Player.person`, one to one). It
holds the handle the boards show, and nothing a part of the project already
knows about the person.

- **A guest.** `POST /api/game/guest/` makes a person with no account, its
  player and a token. The server keeps the token's SHA-256 only. The client
  sends it as `X-Player-Token` (`KARNI_GAME_TOKEN_HEADER`). With an `intent`,
  a retry of a lost answer gives the same guest, with a new token, never a
  second guest. Settings, Games (`allow_guests`) switches guest play off
  (`GAME005`).
- **An account.** A signed-in account plays as the player of the person
  linked to it, made on its first call. An account is linked to a person once
  its email is verified ([people](people.md#the-account-link)), so an
  unverified account is `GAME004` and the game keeps playing as a guest.
- **Guest to account.** `POST /api/game/upgrade/`, signed in and with the
  guest's token, merges the guest's person into the account's person with
  `people.merge`. When the account had no player, the guest's player becomes
  the account's. When it had one, the two are merged by
  `karni_game.merge.Merger`: saves (both copies of a slot are kept), scores
  (the better best of each period), balances (added up, capped), items (a
  union), achievements and missions (progress added up, every unlock kept),
  the streak (the longer) and the rewards claimed (both histories). The
  guest's token is revoked. [The game API](game-api.md#post-upgrade) lists
  every rule.

Staff merging two people (a duplicate found later) merge their players the
same way: the merge hook of `Player` is the people contract's.

**From another origin.** A portal build runs on the portal's domain. List the
origins in `KARNI_GAME_CORS_ORIGINS` and let the browser send the token's
header (`CORS_ALLOW_HEADERS = (*default_headers, "x-player-token")`, from
`corsheaders.defaults`, `GAME038` while it is missing). Only `/api/game/`
answers those origins, and only with a token: the guest's, or an account's
JWT. A session cookie never signs in across origins.

**No endpoint takes a player's id from the client.** Every call finds its
player from the request alone, so one player can never read or change
another player's saves, scores, wallet or items. The module's tests call
every route as a second player and check the first player's rows.

## Saves

A save is a JSON object per player, game and slot, with a **server version
counter**. Every write names the version it started from (`base_version`, `0`
for an empty slot) and makes it one higher. A write from a stale device is
`409 GAME008` with the server's copy, so the client chooses and writes again
on top of it. A device's clock never decides.

- The size is capped per game (`max_save_bytes`, `413 GAME007`) and so are the
  slots (`max_slots`, `GAME011`).
- `schema_version` is the shape of the data, the game's own number. When the
  game's `save_schema_version` is newer, the server runs the game's migrations
  on an older save, when it is read and when it is written:

  ```python
  # games/game.py, imported at startup
  from karni_game import hooks


  @hooks.save_migration("block-hopper", 1)
  def levels_become_a_list(data):
      # version 1 to 2: {"level": 3} becomes {"levels": [1, 2, 3]}
      return {**data, "levels": list(range(1, data.pop("level", 0) + 1))}
  ```

  A newer save than the game knows is `GAME009`. A missing step is `GAME010`.

## Scores and leaderboards

`POST /api/game/<game>/boards/<board>/scores/` sends a score. Before it
counts, the server checks:

1. the player is not banned from the boards (`GAME029`).
2. the value is in the board's plausible range (`min_value` to `max_value`,
   `GAME013`).
3. the run is there when the board has `requires_run`, it is smaller than
   `KARNI_GAME_MAX_RUN_BYTES`, and on a daily board its seed is the day's
   (`GAME014`).
4. a `played_at` (a score played offline, sent later) is inside
   `KARNI_GAME_PLAYED_AT_WINDOW` (`GAME036`): the score is then on the boards
   of the day and week it was played, and a daily board takes that day's seed.
5. the project's run check for the board, when it has one, accepts it.

A score better than `review_beyond`, or one a run check flags, is stored as
`flagged`: it counts on no board until a moderator accepts it. A run (the seed
and the input log) is kept for review when the board has `keep_runs`, so a
deterministic game can replay it:

```python
@hooks.run_check("block-hopper", "high")
def replay(score, run):
    # "accept", "flag" (held for staff) or "reject" (GAME014)
    return "accept" if run and simulate(run["seed"], run["inputs"]) == score else "flag"
```

Each player has one best per board and period: all time, the game's day,
the game's week (from Monday). A tie goes to the earlier score. The board
answers its top (`GET boards/<board>/`) and a player's rank with the players
around them (`GET boards/<board>/me/`). A banned player, an erased person and
a deleted player are on no board. Score submissions are limited per player
(`score` in `KARNI_GAME_RATES`), and a score's `intent` makes a retry count
once.

## Wallet, rewards and the shop

A wallet is a player's balance in one currency. `karni_game.wallet.change`
is the only way it moves: it locks the wallet's row, refuses to go below 0
(`409 GAME016`), credits up to the currency's cap and no further, writes the
balance with a conditional `UPDATE`, and writes a ledger entry with the
amount, the balance after it and the reason (`reward`, `purchase`, `mission`,
`achievement`, `match`, `grant`, `merge`, `refund`). Two purchases at the same
moment never spend the same coins: a test runs them at once on PostgreSQL.

**Rewards** are declared on the server. A client never names an amount:

| Kind | Granted |
|---|---|
| `daily` | with the daily check-in, once a day |
| `ad` | after an ad, by its `trust`: `callback` (the default) only when the portal's server calls back signed, `client` when the client claims it (`POST rewards/<key>/claim/`) within `per_day` and `cooldown` |
| `mission`, `achievement` | when the server completes the mission or unlocks the achievement |
| `match` | when a realtime server's report names it |
| `grant` | by staff |

An ad reward's `trust` is the honest answer to who vouches that the ad was
watched. With `callback` (the default) only the portal's server does, signed.
With `client` the client says so, and any client can, so such a reward is
capped at `KARNI_GAME_CLIENT_CLAIMS_PER_DAY` (5) a day: a blank `per_day`
takes that cap, and a higher one is refused (`GAME026`). Declare `client` only
for a portal without a server callback, and keep the amount small.

### Portal callbacks

An ad portal that confirms a watched ad server to server is declared once:

```python
KARNI_GAME_PORTALS = {"arcade": {"secret": env("ARCADE_PORTAL_SECRET")}}
```

The client asks for an intent (`POST rewards/<key>/intent/`, a token this
server signs, valid for `KARNI_GAME_AD_INTENT_SECONDS`) and hands it to the
portal's ad call. The portal's server posts it back to
`/api/game/callbacks/arcade/` with its event id, signed with
`X-Karni-Timestamp` and `X-Karni-Signature: sha256=<HMAC-SHA256 of
"<timestamp>." + body>`. The reward is granted once per event. A portal that
signs another way gets a verifier class of its own: a subclass of
`karni_game.signatures.HmacVerifier` named in `"verifier"`.

**The shop** sells a game's items for its currency: `POST shop/<item>/buy/`
spends the price and gives the item in one transaction. An item is owned once
(`GAME022`), and one item per slot is equipped (`POST items/<item>/equip/`).

**Real money** goes through [karni-commerce](commerce.md) when the project has
it (`pip install "karni-game[commerce]"`): an item with `real_money` is the
sellable kind `game_item`. The buyer signs in, adds it to the cart
(`{"kind": "game_item", "item": "<its id>"}`), and the item is their player's
once the order is paid, and goes back on a refund. The shop never sells it for
currency (`GAME031`).

## Daily content

The server's date is the game's: a day on the game's `timezone`, never the
device's. `GET /api/game/<game>/daily/` answers the day, when it resets, the
day's **seed** and the daily board. The seed is the same for every player of
the game that day and nobody knows it before (it is derived from the
project's `SECRET_KEY`), so a daily level generated from it is the same for
everyone and cannot be played early by changing the device clock. A board with
`daily_seed` takes only runs on that seed.

`POST daily/check-in/` is once a day: the streak goes on when the last
check-in was yesterday or up to `streak_grace_days` before, starts again at 1
otherwise, and the game's `daily` rewards are granted.
`KARNI_GAME_DAILY_SEED` names another `seed(game, day) -> int`.

## Achievements and missions

The game reports **counters** (`coins_collected`, `levels_done`):
`POST progress/` with `{"events": [{"counter": "coins_collected", "amount":
12}]}`. The server refuses a counter no active achievement or mission of the
game counts, and an amount outside 1 to `max_progress_step` (`GAME024`). It
adds the amounts, then unlocks each achievement whose counter reached its
goal over all time, and completes each mission reached within its period,
granting their rewards. An unlock publishes `game.achievement.unlocked`, is
an entry on the person's timeline, and lands in the account's inbox as the
message `game.achievement_unlocked` while [notifications](notify.md) are
installed. A hidden achievement shows its title once unlocked.

## Remote config, flags and analytics

`GET /api/game/<game>/` is the one call a client makes at boot: the game,
the server's clock, its config values and its flags, its save limits, boards,
currencies and analytics schema. A flag with a rollout below 100 percent is on
for that share of players, the same players every time.

`POST events/` sends analytics events. Each must be one the game's
`analytics` settings declare, with its props and their types, at most 10
props and text up to 100 characters, at most 20 a request (`GAME025` for the
rest), and the endpoint is limited per player. A batch's `intent` makes a
retry publish nothing twice. Each accepted event is
published as the [family event](family-events.md) `game.analytics.tracked`, so
the project's own analytics subscribe to it and store or forward it:

```python
# analytics/listeners.py
from karni.events import Event, subscribe


@subscribe("game.analytics.tracked", version=1)
def keep(event: Event) -> None:
    ...  # event["game"], event["event"], event["props"], event["player"]
```

## Multiplayer: a realtime server of your own

Karni runs no realtime server: a match server is its own service, in any
language. Two calls join it to the players and the boards, and
[the game API](game-api.md#multiplayer-a-realtime-server-of-your-own) is its
contract:

1. **The player token.** `POST <game>/multiplayer/token/` gives the client a
   JSON Web Token (HS256) signed with `KARNI_GAME_SERVER_SECRET` (a long random
   string, at least 32 bytes), valid `KARNI_GAME_TOKEN_SECONDS` (300). The
   client hands it to the game server, which verifies the signature, the
   issuer, the audience `game:<slug>` and the expiry with any JWT library, and
   trusts `sub` as the player's id. A banned player gets none (`GAME029`), and
   without the secret there is no multiplayer (`503 GAME027`).
2. **The results report.** The game server posts a finished match to
   `POST <game>/multiplayer/results/`, signed with the same secret: each row
   a player, optionally a board and a value (checked against the board's
   range) and `match` rewards. A report is recorded whole or not at all, and
   once per match id.

## The admin and the roles

The admin has the games (with their boards, currencies and config values
inline), the rewards, items, achievements and missions, and explicit screens
where staff act:

- **Players**, with their person's name and email: *Ban from the boards*,
  *Unban*, *Revoke the guest token*.
- **Scores**, filtered by status, with each run read only: *Accept* and
  *Reject* for flagged runs. Rejecting a score rebuilds the player's bests.
- **Wallets**, read only, with their ledger inline, and *Grant currency* (an
  amount and a note, a ledger entry per wallet).
- **Ledger entries**, read only.

The module declares two roles: `game-manager` (everything of the games) and
`game-moderator` (the players and the scores: ban and unban, accept and
reject). The same resources are on the API for staff tools
([the game API](game-api.md#staff-resources)). `KARNI_GAME_ROLES = False`
declares neither.

**Erase and impersonation** behave as for any person. `people.erase(person)`
takes the player off every board, names it "Erased player", revokes its
token, and drops its saves, run records and ledger notes. The scores, the
balances and the ledger's amounts stay. A support user acting as someone with
karni-impersonation plays as them, and every player write consults the
vetoes: deleting a save is blocked by the default list, and
`KARNI_IMPERSONATION_BLOCKED += ["karni_game.wallet*"]` blocks spending too.

## The family

| Contract | What karni-game does with it |
|---|---|
| [People](people.md) | A player is a person's profile. A guest is a person without an account. Merge and erase reach the player. The fact `game_last_seen` says when a person last played. |
| [Family events](family-events.md) | `game.player.joined`, `game.player.upgraded`, `game.achievement.unlocked`, `game.mission.completed`, `game.item.bought`, `game.score.flagged`, `game.analytics.tracked`, `game.match.reported` |
| [Timeline](timeline.md) | The upgrade, an unlocked achievement and a bought item are entries on the person's timeline while `karni.timeline` is installed. |
| [Notifications](notify.md) | `game.achievement_unlocked` goes to the account's inbox. |
| [Preferences](preferences.md) | Settings, Games: `allow_guests` and `public_boards` (boards readable without a player). |
| [Commerce](commerce.md) | Real-money items, the sellable kind `game_item`, only when it is installed. |

## A new game project

```sh
karni new "Sky Dash" --kind game --genre runner   # a complete small game from a starter
karni new "Block Hopper" --kind game              # a game first, the small blank start
karni new "Block Hopper" --kind app+game          # an app with the game on a page
```

### One command to a playable game

`--genre runner` starts from the runner starter
([game starters](game-starters.md)): a complete one-tap runner, made as "Sky
Dash", on every layer of `@karni/game` and on this module. `karni starters
list --match "<one line>"` finds the starter for a request.

```sh
pip install karni karni-cli karni-game
karni new "Sky Dash" --kind game --genre runner && cd sky_dash
cp .env.example .env && docker compose up -d
karni migrate && karni load content/game.yaml
(cd game/sky-dash && npm install && npm run dev)  # http://localhost:5174/play/sky-dash/
```

1. **Loading, then the title.** The loading scene opens the session: the
   portal, the guest player, the save slots, today's seed and the wallet.
   The title shows the bests, the coins and today's run.
2. **A run.** Space or a tap jumps, and again in the air jumps twice. The
   rules in `game/sky-dash/src/rules/` are a simulation, so the track comes
   from the run's seed and every run is recorded as its seed and inputs.
3. **Game over.** The score goes to the `distance` board with its run, and
   `games/game.py` checks the run before the score counts. The board's top
   five come back to the game-over panel. A rewarded ad buys one continue
   a run, through the server's `continue` reward, three a day.
4. **Today's run.** Everyone plays the server's seed of the day, and its own
   board takes only a run on that seed.
5. **The shop.** The coins of the daily gift, the missions, the
   achievements and the ads buy two trails and two hats. The prices and the
   balance are the server's.
6. **The checks.** `npm test` and `npm run check-rules` in the game,
   `npm run smoke` in a headless browser, and `karni test` for the server,
   which proves that one player never reaches another's saves, scores or
   wallet. `npm run package` makes one package per portal.

The game's files are the project's own, and only the game's own code is in
them: the rules, the scenes, the drawing, the sounds and the content. The
rest is imported from `@karni/game`.

### The blank start and the app with a game

Both kinds write the game's server side:

- karni-game wired as `karni add game` wires it, `KARNI_PEOPLE = True` and
  the include in `config/urls.py`.
- a `games` app: `games/game.py` for the save migrations and run checks, and
  tests that a guest boots the game, saves and scores, that a finished run
  unlocks the first achievement, and that one player never sees another's
  save or wallet.
- `content/game.yaml`: the game, a board and a daily board, a currency with
  daily, ad, achievement and mission rewards, an item, two achievements, a
  mission and config. Run `karni load content/game.yaml` after `karni
  migrate`, and again after each change.
- the CORS lines a portal package needs: `KARNI_GAME_CORS_ORIGINS` (read
  from the environment in `config/settings.py`) and `CORS_ALLOW_HEADERS`
  sending `x-player-token`.

**`--kind game`** makes the game the front door, with no React staff app
unless `--staff-app` ([apps and games](apps-and-games.md) has the layout and
how it is served):

- `game/block-hopper/` (the blank start, `--genre blank`, the default), the game as its own npm package on
  [`@karni/game`](game-client.md): `src/rules/` (the rules as plain
  functions: a world made from a seed, a run replayed from its seed and input
  log), `tests/` (the rules' tests, `npm test`), `src/play.ts` (the canvas,
  the loop and the input), `src/session.ts` (the portal, the data client, and
  what a finished run reports: a score with its run, progress, a save and an
  analytics event) and the page, `index.html` and `src/main.ts`.
- served at `/play/block-hopper/`, with `/` going there: by its Vite dev
  server in development (`npm run dev`, or the `game` service of
  `docker-compose.yml`), and by the production web front from its build. The
  page calls the game API on its own origin.
- `npm run package` builds, checks and zips one package per portal that
  needs no id of the project's (web, itch.io, Poki, CrazyGames). A package
  calls the game API named by `KARNI_GAME_API_URL` with the guest's token, and
  plays on the device without it.

**`--kind app+game`** writes an app project (the API, the admin, the React
app) with the game inside it, as `--kind game` did in Karni 0.6.0:

- a small game to start from, the project's own code in `frontend/src/game/`
  on [`@karni/game`](game-client.md), which `frontend/package.json` names:
  `rules.ts`, `play.ts` and `session.ts` as above, and `useGame.ts` and
  `Hud.tsx` for the page.
- `frontend/src/pages/game.tsx`, a public page at `/game`: the canvas, the
  player, the wallet and the shop, the daily check-in, the board and the
  achievements. The calls go through the app's own API client, so a
  signed-in player's carry the account. A guest keeps their progress by
  signing in with a code sent by email (`KARNI_EMAIL_OTP = True`): the page
  then calls `POST upgrade/`.
- `frontend/portal/`, the same game alone for the game portals: `npm run
  game:package` builds, checks and zips one package per portal, and
  `--portal gamedistribution` or `--portal y8` adds one once its ids are in
  the build environment ([building for portals](game-client.md#building-for-portals)).
- `karniGame({ relativeBase: false })` from `@karni/game/vite` in
  `frontend/vite.config.ts` (the page's portal module, while the app keeps
  its own base) and its types in `frontend/src/vite-env.d.ts`.

The kind is recorded in pyproject.toml (`kind = "game"` or `kind =
"app+game"`), and `karni context` and the agent files state it. A project
that 0.6.0 made with `--kind game` keeps working and is read as `app+game`
([migrating to 0.7](migrations/0.7.md#the-game-kind-makes-a-game-first)). A
project made without a game kind names neither karni-game nor `@karni/game`.

## Settings

| Setting | Default | What |
|---|---|---|
| `KARNI_GAME_RATES` | see [the game API](game-api.md#rate-limits) | The rate of each limited write, by scope, over the defaults. `None` turns one off. |
| `KARNI_GAME_TOKEN_HEADER` | `X-Player-Token` | The header a guest sends its token in. |
| `KARNI_GAME_CORS_ORIGINS` | `[]` | The origins a portal build calls the game API from, or `"*"`. Tokens only, never cookies. |
| `KARNI_GAME_SERVER_SECRET` | blank | The secret a realtime server shares: it signs the player tokens and the results reports. Blank: no multiplayer. |
| `KARNI_GAME_TOKEN_ISSUER` | `karni-game` | The `iss` of the player token. |
| `KARNI_GAME_TOKEN_SECONDS` | `300` | How long a player token lives. |
| `KARNI_GAME_PORTALS` | `{}` | The portals that call back after an ad: `{name: {"secret", "verifier"}}`. |
| `KARNI_GAME_SIGNATURE_TOLERANCE` | `300` | How far a signed request's timestamp may be from the server's clock, in seconds. |
| `KARNI_GAME_AD_INTENT_SECONDS` | `3600` | How long an ad reward's intent is valid. |
| `KARNI_GAME_CLIENT_CLAIMS_PER_DAY` | `5` | The most claims a day of an ad reward the client claims (`trust: client`). |
| `KARNI_GAME_INTENT_DAYS` | `7` | How long a write's retry key is kept (the task `karni_game.tasks.prune_intents`). |
| `KARNI_GAME_MAX_SAVE_BYTES` | `1048576` | The largest save any game may allow. |
| `KARNI_GAME_MAX_RUN_BYTES` | `262144` | The largest run record a score may carry. |
| `KARNI_GAME_PLAYED_AT_WINDOW` | `86400` | How far back a score's `played_at` is trusted, in seconds. |
| `KARNI_GAME_MERGER` | `karni_game.merge.Merger` | The class with the merge rules of two players. |
| `KARNI_GAME_DAILY_SEED` | `karni_game.daily.daily_seed` | The function that gives a game's seed of a day. |
| `KARNI_GAME_AUTODISCOVER` | `True` | Import each app's `game.py` at startup. |
| `KARNI_GAME_ROLES` | `True` | Declare the roles `game-manager` and `game-moderator`. |

## Escape hatches

- Every declaration is a row: change it in the admin, or in the content file.
- `KARNI_GAME_MERGER`: a subclass of `Merger` with another rule for one part
  (`merge_saves` keeping only the newest, say).
- `KARNI_GAME_DAILY_SEED`: a curated seed list instead of a derived one.
- A run check per board, a save migration per schema version, in
  `<app>/game.py`.
- A verifier class per portal, `KARNI_GAME_PORTALS[<name>]["verifier"]`.
- The views of `karni_game.api` are plain DRF views: subclass one and mount it
  in place of the include. `GameView` gives a view of your own the same player
  and errors.
- The service modules (`players`, `saves`, `scores`, `wallet`, `rewards`,
  `shop`, `daily`, `progress`, `config`, `multiplayer`) are what the views
  call, and a project's own code calls them the same way.

## What it does not do

- It runs no realtime server and no game loop. A match server is a service of
  the project's own, joined by the token and the report above.
- It does not simulate a game. A score is checked against its board's range,
  its run's size and seed, and the project's run check: replaying a run is the
  game's own code, in a run check.
- It holds no real money. Real money is karni-commerce's.
- It has no chat, no friends list, no moderation of text players write, and
  no level sharing.
- It does not store analytics: it checks and publishes them, and the
  project's subscriber keeps them where it wants.
- It does not trust the device's clock, and has no offline time of its own:
  the client queues what it could not send, with its intents.

## Codes

| Code | When |
|---|---|
| [GAME001](errors.md#game001) | karni-game without the people contract |
| [GAME002](errors.md#game002) to [GAME035](errors.md#game035) | the game API's refusals, each in [the game API](game-api.md#errors) |
| [GAME010](errors.md#game010) | a save migration is missing |
| [GAME026](errors.md#game026) | a game's settings, or a declared row, the server cannot use |
| [GAME030](errors.md#game030) | `karni_game.urls` is not included |
| [GAME032](errors.md#game032) | a save migration or a run check registered wrongly |
| [GAME038](errors.md#game038) | other origins may call the game API, and `CORS_ALLOW_HEADERS` leaves out the token's header |
