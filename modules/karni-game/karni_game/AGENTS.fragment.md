## Games (karni-game)
- The server side of a game. Mount it with `path("api/game/", include("karni_game.urls"))`
  before `path("api/", include("karni.api.urls"))`. The client's contract is docs/game-api.md.
- A player is the game profile of a `karni.people` Person (`Player.person`). Never write a
  player, profile, save, score, wallet or ledger model of your own.
- The server decides: never accept coins, XP, an unlock or a price from a client. Change a
  balance only through `karni_game.wallet` (atomic, capped, a ledger entry with a reason).
- Find the player from the request (`GameView.player`), never from an id the client sends.
- Declare a game, its boards, currencies, rewards, items, achievements and missions as rows
  (the admin, or `karni load content/game.yaml`). A board's `min_value`/`max_value` is its
  plausible range.
- Save migrations and run checks go in `<app>/game.py`: `@hooks.save_migration("<game>", n)`
  and `@hooks.run_check("<game>", "<board>")`.
- React to the game with the family events (`game.achievement.unlocked`,
  `game.analytics.tracked`, ...) in your `listeners.py`.
- A realtime server is your own service: it verifies the HS256 player token with
  `KARNI_GAME_SERVER_SECRET` and reports results to `POST <game>/multiplayer/results/`, signed.
