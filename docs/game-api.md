---
description: "The HTTP contract of karni-game (experimental): every endpoint a game client, a realtime game server and a portal call, with paths, methods, request and response bodies, how a player is identified, the error codes and the rate limits."
---

# The game API (karni-game)

!!! warning "Experimental"
    karni-game and this contract are [experimental](stability.md#experimental-names):
    a path or a field may change in a minor release, with a CHANGELOG entry.
    The error codes keep their meaning.

This page is the contract between the server side of the game add-on
([karni-game](game.md)) and the code that calls it: the `@karni/game` client
in the browser, a realtime game server, and an ad portal's server. Every path
below is under the prefix the project mounts:

```python
# config/urls.py
path("api/game/", include("karni_game.urls")),
```

Bodies are JSON (`Content-Type: application/json`). Times are ISO 8601 in
UTC (`2026-11-19T08:30:00Z`). A day is a date (`2026-11-19`) on the game's
own clock (`timezone` in the game's settings, UTC by default). Scores and
currency amounts are whole numbers. A time is a score in milliseconds.

## Who is calling: the player

A game's progress belongs to a **player**. A player is the game profile of a
[person](people.md). Every player endpoint finds the player from the request
alone. No endpoint takes a player's id from the body, the path or the query,
so one player can never read or change another player's saves, scores,
wallet or items.

| The request carries | The player is |
|---|---|
| A signed-in account (the project's JWT `Authorization: Bearer ...`, or its session cookie with the CSRF header) | The player of the person linked to the account, made on the first call. The account's email must be verified, since a person is linked to an account only then (`GAME004`). |
| No account, and `X-Player-Token: <token>` | The guest the token was issued to (`POST guest/`). An unknown or revoked token is `GAME003`. |
| Neither | No player: an endpoint that needs one answers `GAME002`. |

When a request carries both, the account wins and the token is read only by
`POST upgrade/`.

A guest token is a secret. Keep it where the game keeps its local save, send
it only in the header, and drop it once the guest is upgraded: the server
revokes it then.

## Errors

An error the server decides answers this body, with the status in the tables
below:

```json
{
  "detail": "GAME008: The save changed on the server since version 3. See https://.../errors/#game008",
  "code": "GAME008"
}
```

Some errors add fields (the server's copy of a save, the time a reward is
available again). A `400` without `code` is a body that does not validate:
each field names its messages, `{"value": ["A valid integer is required."]}`.
A `404` without `code` is a path that does not exist (a missing save is
`GAME037`).

| Code | Status | When |
|---|---|---|
| `GAME002` | 401 | The endpoint needs a player, and the request names none. |
| `GAME003` | 401 | The guest token is unknown or revoked. |
| `GAME004` | 403 | The account's email is not verified, so no person is linked to it yet. |
| `GAME005` | 403 | Guest play is off for the project (Settings, Games: `allow_guests`). |
| `GAME006` | 404 | No active game has this slug. |
| `GAME007` | 413 | The save is larger than the game allows (`max_save_bytes`). The body has `size` and `max_bytes`. |
| `GAME008` | 409 | A stale save: `base_version` is not the server's version. The body has `save`, the server's copy. |
| `GAME009` | 400 | The save's `schema_version` is newer than the game's, or below 1. |
| `GAME011` | 400 | The slot name is not one (`[a-z0-9][a-z0-9_-]{0,39}`), or the player has `max_slots` slots already. |
| `GAME012` | 404 | No active board has this key in the game. |
| `GAME013` | 400 | The score is outside the board's plausible range (`min_value`, `max_value`). |
| `GAME014` | 400 | The run is missing where the board needs one, too large, or its seed is not today's on a daily board. |
| `GAME015` | 429 | Too many requests of this kind. The body has `retry_after` (seconds), and the `Retry-After` header says the same. |
| `GAME016` | 409 | Not enough of the currency. The body has `balance` and `needed`. |
| `GAME017` | 409 | The reward is not available now. The body has `next_at` (or `null` when it never is again). |
| `GAME018` | 403 | The reward is granted only by the portal's signed callback, not by the client. |
| `GAME019` | 403 | A server-to-server request whose signature or timestamp does not verify. |
| `GAME020` | 400 | An intent token (an ad reward's) that is not valid or has expired. |
| `GAME021` | 404 | No item has this key in the game's shop, or it is not for sale. |
| `GAME022` | 409 | The player owns the item already. |
| `GAME023` | 409 | The player does not own the item. |
| `GAME024` | 400 | A progress event names a counter no achievement or mission of the game counts, or its amount is not 1 to `max_progress_step`. The body has `index`, the event. |
| `GAME025` | 400 | Every analytics event of the request was refused (some refused: 202, each named in `rejected`). The body has `rejected`. |
| `GAME027` | 503 | Multiplayer is not set up: the project has no `KARNI_GAME_SERVER_SECRET`. |
| `GAME028` | 409 | The upgrade cannot happen: no guest token, the token is not a guest's, or the two people cannot be merged. |
| `GAME029` | 403 | The player is banned from the boards: no score, no realtime token. |
| `GAME031` | 400 | The item is sold for real money, through the cart of karni-commerce, not for currency. |
| `GAME033` | 409 | The `intent` was used already with another body. |
| `GAME035` | 400 | A results report names a player, a board or a reward the game does not have. The body has `index`, the row. |
| `GAME036` | 400 | A score's `played_at` is older than `KARNI_GAME_PLAYED_AT_WINDOW` or more than a minute ahead of the server. The body has `window` (seconds). |
| `GAME037` | 404 | The player has no save in this slot (a path that does not exist is a 404 without `code`). |

## Rate limits

Writes are limited per player (a guest token's issue per client address, a
server's reports per game). Past the limit the answer is `429 GAME015`. The
project changes a rate in `KARNI_GAME_RATES` (`None` turns one off). Reads
have the project's own limits only (`anon` and `user`).

| Scope | Endpoints | Default |
|---|---|---|
| `guest` | `POST guest/` | 10 per hour per client address |
| `save` | `PUT` and `DELETE saves/<slot>/` | 60 per minute |
| `score` | `POST boards/<board>/scores/` | 30 per minute |
| `progress` | `POST progress/` | 60 per minute |
| `events` | `POST events/` | 30 per minute |
| `claim` | `POST rewards/<key>/claim/`, `POST rewards/<key>/intent/`, `POST daily/check-in/` | 30 per minute |
| `buy` | `POST shop/<item>/buy/`, `POST items/<item>/equip/` and `unequip/` | 30 per minute |
| `token` | `POST multiplayer/token/` | 20 per minute |
| `results` | `POST multiplayer/results/` | 600 per minute per game |
| `callback` | `POST callbacks/<portal>/` | 600 per minute per portal |

## Retries: `intent`

A write that makes a guest, changes a score, a wallet or progress, or sends
analytics takes an optional `intent`: a string of 8 to 64 letters, digits, `_` or `-` that the client
makes once per action (a UUID is fine) and sends again on every retry of that
action. The first request does the work. A retry with the same `intent` and
the same body does nothing again and answers the first answer, with
`"replayed": true`. The same `intent` with another body is `409 GAME033`.
An offline queue keeps the `intent` with each queued write. Intents are kept
for `KARNI_GAME_INTENT_DAYS` (7).

## Players

### `POST guest/`

Issues a guest: a person with no account, its player and a token. No
sign-in. Limited by `guest`. Refused with `GAME005` when guest play is off.

Request (optional): `{"handle": "Swift Fox", "intent": "boot-6f1c..."}`.
Without a handle the server names the guest (`Player 4821`).

`intent` makes a lost answer safe to retry: a retry within an hour with the
same `intent` and handle answers `200` with the same player, `"replayed":
true` and a new token (the server never keeps a token, so the lost one stops
working). The same `intent` with another handle, or after an hour, is
`409 GAME033`.

`201`:

```json
{
  "token": "gt_5y7Q...",
  "player": {"id": "8b4e...", "handle": "Swift Fox", "guest": true, "created_at": "2026-11-19T08:30:00Z"}
}
```

### `GET me/` and `PATCH me/`

The calling player. `PATCH` takes `{"handle": "..."}`: 2 to 32 characters,
letters, digits, spaces, `_`, `-` and `.`.

`200`: the `player` object above.

### `POST upgrade/`

A guest who signed in keeps their progress. The request carries the account
(signed in, email verified) and the guest's token, in `X-Player-Token` or as
`{"guest_token": "gt_..."}`. The guest's person is merged into the account's
person ([people](people.md#merge)), the guest's progress joins the account's
player, and the token is revoked.

When the account has no player yet, the guest's player becomes the
account's, with everything on it. When it has one, the two are merged:

| What | Rule |
|---|---|
| Saves | A slot only the guest has moves. A slot both have: the copy written last keeps the slot, the other moves to `<slot>-merged` (or `-merged-2` and on), so nothing is lost. Both are listed in `merged.saves.kept_both`. |
| Scores | Every score moves. Each board keeps the better best of the two for every period. |
| Wallet | Each currency's balances add up, capped at the currency's cap. The ledger records the move on both wallets (`reason: "merge"`). |
| Items | The account owns every item either owned. What the account has equipped stays equipped. The guest's choice is used for a slot the account left empty. |
| Achievements and missions | The progress of each counter adds up. An unlock or a completed mission of either stays, with the earlier time. |
| Daily streak | The longer streak stays, and the best of the two. |
| Rewards claimed | Both histories stay, so a daily reward is not claimed twice on one day by merging. |

`200`:

```json
{
  "player": {"id": "2c1f...", "handle": "Swift Fox", "guest": false, "created_at": "..."},
  "merged": {
    "adopted": false,
    "saves": {"moved": 1, "kept_both": ["main"]},
    "scores": 14,
    "currencies": {"coins": 120},
    "items": 2,
    "unlocks": 3,
    "streaks": 1,
    "claims": 4
  }
}
```

Errors: `GAME002` (no account), `GAME004`, `GAME003` (the token), `GAME028`.

## A game

### `GET <game>/`

The one call a client makes at boot, and again whenever it wants fresh
config. No player is needed. With one, the flags are worked out for that
player.

`200`:

```json
{
  "game": {"slug": "block-hopper", "title": "Block Hopper"},
  "server": {"time": "2026-11-19T08:30:00Z", "date": "2026-11-19", "timezone": "UTC", "resets_at": "2026-11-20T00:00:00Z"},
  "config": {"jump_height": 3.5, "levels": ["meadow", "cave"]},
  "flags": {"night_mode": true, "new_shop": false},
  "save": {"schema_version": 2, "max_bytes": 65536, "max_slots": 5},
  "boards": [{"key": "high", "title": "High score", "order": "desc", "periods": ["all", "daily", "weekly"], "requires_run": false, "daily_seed": false}],
  "currencies": [{"key": "coins", "title": "Coins", "cap": 99999}],
  "analytics": {"level_started": {"level": "int"}, "level_done": {"level": "int", "ms": "int"}}
}
```

`config` holds the values staff set (any JSON). `flags` holds every feature
flag as `true` or `false`. A flag with a rollout below 100 percent is on for
that share of players, the same players every time (a hash of the player and
the flag). Without a player such a flag is off.

## Saves

A save is one JSON document per player, game and slot. The server counts
its versions: every write makes `version` one higher, and a write names the
version it was based on, so a stale write from another device never wins.

The save object:

```json
{"slot": "main", "version": 4, "schema_version": 2, "size": 812, "data": {"level": 7}, "updated_at": "..."}
```

`schema_version` is the shape of `data`, the game's own number. When the
game's settings say a newer one, the server runs the game's migrations
(version n to n + 1, each a function the project registers) on a save that
is older, when it is read and when it is written, and stores the result.

### `GET <game>/saves/`

`200`: `{"results": [<save without data>], "max_slots": 5, "max_bytes": 65536}`.

### `GET <game>/saves/<slot>/`

`200`: the save. `404 GAME037` when the player has no save in the slot.

### `PUT <game>/saves/<slot>/`

Request:

```json
{"data": {"level": 8}, "schema_version": 2, "base_version": 4}
```

`base_version` is the version this write starts from: the `version` the
client read, or `0` for a slot it believes is empty. Limited by `save`.

- `200`: the save as stored, `version` one higher.
- `409 GAME008`: the server has another version. The body has `save`, the
  server's copy, so the client can choose and write again on top of it.
- `413 GAME007`, `400 GAME009`, `400 GAME011`.

### `DELETE <game>/saves/<slot>/?base_version=4`

`204`, or `404 GAME037` when the slot is empty. `409 GAME008` when
`base_version` is given and is not the server's.

## Scores and boards

A board has an order (`desc`: higher is better, `asc`: lower is better, for
a time), the periods it keeps (`all`, `daily`, `weekly`, on the game's
clock, a week from Monday), a plausible range, and whether a score must come
with its run. Each player has one best per board and period. Ties go to the
earlier score.

### `POST <game>/boards/<board>/scores/`

Request:

```json
{
  "value": 1200,
  "intent": "3f8c2a90-run-17",
  "played_at": "2026-11-18T23:58:10Z",
  "run": {"seed": "20261119", "inputs": [[0, "jump"], [412, "left"]], "duration_ms": 52000, "build": "1.4.0", "meta": {"level": "cave"}}
}
```

`run` is optional unless the board has `requires_run`. It is kept for staff
to review when the board keeps runs: the seed and the input log let a
deterministic game replay the run. Limited by `score`.

`played_at` is optional: when the score was played, for a score played offline
and sent later. The server trusts it inside `KARNI_GAME_PLAYED_AT_WINDOW`
(86400 seconds by default) and up to a minute ahead of its clock (`GAME036`
outside). The score is then on the daily and weekly boards of that day, ties
go by it, and on a board with `daily_seed` the run's `seed` must be that day's
(`GET daily/` on that day). Without it the score is played now.

`201` (`200` and `"replayed": true` for a retried `intent`):

```json
{
  "score": {"id": "61ad...", "value": 1200, "status": "accepted", "created_at": "..."},
  "best": {"all": {"value": 1350, "rank": 12}, "daily": {"value": 1200, "rank": 3}},
  "improved": ["daily"]
}
```

`status` is `accepted`, or `flagged`: the score is held for staff (above the
board's `review_above`, or the project's run check said so), counts on no
board until staff accept it, and `best` does not include it.

Errors: `GAME012`, `GAME013`, `GAME014`, `GAME029`, `GAME033`, `GAME036`, `GAME015`.

### `GET <game>/boards/<board>/?period=all&limit=10`

No player is needed (the project can require one: Settings, Games,
`public_boards`). `limit` is 1 to 100 (10).

`200`:

```json
{
  "board": {"key": "high", "title": "High score", "order": "desc", "periods": ["all", "daily", "weekly"]},
  "period": "all",
  "period_start": null,
  "entries": [{"rank": 1, "handle": "Swift Fox", "value": 5400, "achieved_at": "...", "me": false}],
  "me": {"rank": 12, "value": 1350}
}
```

`period_start` is the day of a daily board's entries or the Monday of a
weekly one's. `me` is `null` without a player or without a score. A banned
or erased player is not listed.

### `GET <game>/boards/<board>/me/?period=all&around=3`

The player's rank and the `around` (0 to 25) players above and below.

`200`: `{"period": "all", "period_start": null, "rank": 12, "value": 1350, "entries": [...]}`,
with `rank` and `value` `null` and no entries when the player has no score.

## Wallet, ledger and items

Currencies are the game's soft currencies (coins, gems). Only the server
changes a balance: a reward, a purchase, a mission, a staff grant, a match
result. A balance never goes below 0 or above the currency's cap, and every
change is a ledger entry with its reason.

### `GET <game>/wallet/`

`200`:

```json
{
  "balances": [{"currency": "coins", "title": "Coins", "balance": 120, "cap": 99999}],
  "items": [{"item": "red-cap", "title": "Red cap", "slot": "hat", "equipped": true, "acquired_at": "..."}]
}
```

### `GET <game>/wallet/ledger/?currency=coins&page=1`

The player's own entries, newest first, 50 a page.

`200`: `{"count": 31, "next": 2, "results": [{"id": "...", "currency": "coins", "amount": -50, "balance_after": 120, "reason": "purchase", "reference": "red-cap", "created_at": "..."}]}`.
`reason` is one of `reward`, `purchase`, `mission`, `achievement`, `match`, `grant`, `merge`, `refund`.

### `GET <game>/shop/`

`200`: `{"results": [{"key": "red-cap", "title": "Red cap", "slot": "hat", "price": {"currency": "coins", "amount": 50}, "real_money": false, "owned": false, "equipped": false}]}`.
A real-money item has `"price": null` and `"real_money": true`: it is sold
through the cart of karni-commerce when the project has it (kind
`game_item`, the item's id), and the item is the buyer's player's once the
order is paid.

### `POST <game>/shop/<item>/buy/`

Request (optional): `{"intent": "..."}`. Limited by `buy`.

`201`: `{"item": {"key": "red-cap", "slot": "hat", "equipped": false}, "balance": {"currency": "coins", "balance": 70}}`.

Errors: `GAME021`, `GAME022`, `GAME016`, `GAME031`, `GAME033`.

### `POST <game>/items/<item>/equip/` and `POST <game>/items/<item>/unequip/`

`200`: `{"item": "red-cap", "slot": "hat", "equipped": true}`. Equipping an
item takes off the item that was in its slot. `GAME023` for an item the
player does not own.

## Rewards

A reward is declared on the server: its kind, its currency and amount, how
often it may be claimed. The client never names an amount.

| Kind | How it is granted |
|---|---|
| `daily` | `POST daily/check-in/`, once per day. |
| `ad` | After an ad: `POST rewards/<key>/claim/`, or only through the portal's signed callback when the reward has `callback`. |
| `mission`, `achievement` | When the mission is completed or the achievement unlocked. |
| `match` | When a realtime server reports a result that names it. |
| `grant` | By staff only. |

### `GET <game>/rewards/`

`200`: `{"results": [{"key": "ad-coins", "title": "Watch for coins", "kind": "ad", "currency": "coins", "amount": 25, "callback": false, "per_day": 5, "claimed_today": 2, "available": false, "next_at": "2026-11-19T08:35:00Z"}]}`.

### `POST <game>/rewards/<key>/claim/`

Request (optional): `{"intent": "..."}`. Limited by `claim`. For an `ad`
reward without `callback` (`daily` rewards come with the check-in).

`200`: `{"granted": {"currency": "coins", "amount": 25, "balance": 145}, "capped": false, "next_at": "..."}`.
`capped` is true when the cap took some of the amount.

Errors: `GAME017` (with `next_at`), `GAME018`, `GAME033`.

### `POST <game>/rewards/<key>/intent/`

For an `ad` reward with `callback`. `201`: `{"intent": "Ijg...:1tX...", "expires_at": "..."}`.
The client hands `intent` to the portal's ad call as its custom data, and the
portal's server sends it back in the callback below. It is valid for an hour.

### `POST callbacks/<portal>/` (server to server)

The portal's server, once the ad was watched. Signed (see
[signatures](#signatures)) with the portal's secret from `KARNI_GAME_PORTALS`.

Request: `{"intent": "Ijg...:1tX...", "event_id": "the portal's id for this view"}`.

`200`: `{"granted": true, "duplicate": false}`. The same `event_id` again
grants nothing and answers `"duplicate": true`. Errors: `GAME019`, `GAME020`,
`GAME017`.

## Daily content

### `GET <game>/daily/`

`200`:

```json
{
  "date": "2026-11-19",
  "seed": 1738294011,
  "server_time": "...",
  "resets_at": "2026-11-20T00:00:00Z",
  "board": "daily",
  "streak": {"current": 3, "best": 5, "last_day": "2026-11-18", "checked_in": false},
  "rewards": [{"key": "daily-coins", "currency": "coins", "amount": 10}]
}
```

`seed` is the same for every player of the game on that day and unknown
before it. `board` is the game's daily board (one with `daily_seed`), or
`null`. Without a player `streak` is `null`.

### `POST <game>/daily/check-in/`

Once per day: the streak moves on and the daily rewards are granted. A
streak goes on when the last check-in was yesterday, or up to
`streak_grace_days` (1) days before that, and starts again at 1 otherwise.
A second check-in on the same day changes nothing. Limited by `claim`.

`200`: `{"new_day": true, "streak": {...}, "granted": [{"reward": "daily-coins", "currency": "coins", "amount": 10, "balance": 155}]}`.

## Achievements and missions

Both count **counters** the game reports (`coins_collected`, `levels_done`).
An achievement unlocks once its counter reaches its goal, over all time. A
mission does the same within its period (`once`, `daily`, `weekly`) and
grants its reward each time it is completed. The server unlocks and grants:
the client only reports.

### `POST <game>/progress/`

Request:

```json
{"intent": "lvl-7-done", "events": [{"counter": "coins_collected", "amount": 12}, {"counter": "levels_done", "amount": 1}]}
```

At most 20 events. Limited by `progress`.

`200`:

```json
{
  "counters": {"coins_collected": 312, "levels_done": 7},
  "unlocked": [{"key": "collector", "title": "Collector"}],
  "completed": [{"key": "daily-levels", "title": "Three levels today", "granted": {"currency": "coins", "amount": 30, "balance": 185}}]
}
```

An unlocked achievement and a completed mission carry `granted` when they
have a reward. Errors: `GAME024`, `GAME033`.

### `GET <game>/achievements/`

`200`: `{"results": [{"key": "collector", "title": "Collector", "description": "...", "hidden": false, "counter": "coins_collected", "goal": 300, "progress": 312, "unlocked_at": "..."}]}`.
A hidden achievement shows its title and description only once unlocked.

### `GET <game>/missions/`

`200`: `{"results": [{"key": "daily-levels", "title": "Three levels today", "period": "daily", "period_start": "2026-11-19", "counter": "levels_done", "goal": 3, "progress": 1, "completed_at": null, "reward": {"currency": "coins", "amount": 30}}]}`.

## Analytics

### `POST <game>/events/`

Request:

```json
{"intent": "batch-2c9a...", "events": [{"name": "level_started", "props": {"level": 3}}]}
```

`intent` (optional) makes a retried batch publish nothing twice: the retry
answers the first answer with `"replayed": true` (with a player, keyed by the
player, without one, among the calls without one).

At most 20 events, each a name the game's `analytics` settings declare with
its props and their types (`int`, `float`, `str`, `bool`), at most 10 props,
text up to 100 characters. Each accepted event is published as the family
event `game.analytics.tracked` ([family events](family-events.md)), for the
project's own analytics to subscribe to. Limited by `events`.

`202`: `{"accepted": 1, "rejected": [{"index": 1, "code": "GAME025", "detail": "..."}]}`.
`400 GAME025` when every event was refused.

## Multiplayer (a realtime server of your own)

Karni runs no realtime server. A game server of the project's own (any
language) trusts Karni for who the player is, and reports results back.

### `POST <game>/multiplayer/token/`

A short-lived token the client hands to the game server when it connects.
Limited by `token`. `GAME029` for a banned player.

`201`: `{"token": "eyJhbGciOiJIUzI1NiIs...", "expires_at": "...", "player": {"id": "8b4e...", "handle": "Swift Fox"}}`.

The token is a JSON Web Token signed with HS256 and `KARNI_GAME_SERVER_SECRET`,
which the game server shares. Its claims:

| Claim | Holds |
|---|---|
| `iss` | `KARNI_GAME_TOKEN_ISSUER` (`karni-game`) |
| `aud` | `game:<slug>` |
| `sub` | the player's id |
| `name` | the handle |
| `guest` | `true` for a guest |
| `iat`, `exp` | issued, and expires `KARNI_GAME_TOKEN_SECONDS` (300) later |
| `jti` | a random id, for the game server to refuse a token twice |

The game server verifies the signature, `iss`, `aud` and `exp` with any JWT
library, and uses `sub` as the player's id in its report.

### `POST <game>/multiplayer/results/` (server to server)

The game server's report of a finished match. Signed with
`KARNI_GAME_SERVER_SECRET` (see [signatures](#signatures)). Limited by
`results`.

Request:

```json
{
  "match": "arena-2026-11-19-0042",
  "results": [
    {"player": "8b4e...", "board": "arena", "value": 1200, "rewards": ["match-win"]},
    {"player": "2c1f...", "board": "arena", "value": 900}
  ]
}
```

Each row may name a board and a value (a score, checked against the board's
range, never held back by the per-player limit) and rewards of kind
`match`. The report is recorded whole or not at all. A banned player's score
is left out, and the rest of their row is recorded.

`200`: `{"match": "arena-2026-11-19-0042", "recorded": 2, "duplicate": false}`.
The same `match` again records nothing and answers `"duplicate": true`.
Errors: `GAME019`, `GAME035`, `GAME013`.

## Signatures

A server-to-server request carries two headers:

```text
X-Karni-Timestamp: 1763541000
X-Karni-Signature: sha256=<hex of HMAC-SHA256(secret, "<timestamp>." + raw body)>
```

The timestamp is Unix seconds and must be within 300 seconds of the
server's clock. The signature covers the exact bytes of the body. A request
that fails either check answers `403 GAME019` and changes nothing.

A portal whose callback is signed another way gets a verifier class of its
own (`KARNI_GAME_PORTALS`, [game](game.md#portal-callbacks)).

## Staff resources

Staff read and change the game through the project's API and admin, by the
grants of their roles (`karni_game.<model>:<action>`). The roles
`game-manager` (everything) and `game-moderator` (players, scores and
flagged runs) are declared by the module.

| Endpoint | What |
|---|---|
| `/api/games/` | the games, their settings, config and flags |
| `/api/game-boards/`, `/api/game-currencies/`, `/api/game-rewards/`, `/api/game-items/`, `/api/game-achievements/`, `/api/game-missions/`, `/api/game-config/` | what each game declares |
| `/api/game-players/` | the players with their person. `POST {id}/ban/`, `POST {id}/unban/`, `POST {id}/revoke-token/` |
| `/api/game-scores/?status=flagged` | every score and its run. `POST {id}/accept/`, `POST {id}/reject/` |
| `/api/game-wallets/` | the balances. `POST {id}/grant/` with `{"amount": 50, "note": "..."}` (negative takes away) |
| `/api/game-ledger/` | every ledger entry |
| `/api/game-saves/` | the saves, read only |
| `/api/game-streaks/`, `/api/game-unlocks/`, `/api/game-matches/` | the daily streaks, who unlocked what, the matches reported, read only |
