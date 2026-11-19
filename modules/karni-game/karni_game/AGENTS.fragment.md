## Games (karni-game)
- The server side of a game: `path("api/game/", include("karni_game.urls"))` before the
  API include, `KARNI_PEOPLE = True`. The client's contract is docs/game-api.md.
- Never write a player, save, score, wallet, ledger or achievement model of your own. A
  player is `Player.person` (karni.people). Find it from the request, never from an id.
- The server decides: never accept coins, XP, an unlock or a price from a client. A balance
  moves only through `karni_game.wallet.change` (atomic, capped, a ledger entry).
- Declare the game, its boards (`min_value`/`max_value` is the plausible range), currencies,
  rewards, items, achievements and missions in `content/game.yaml` (`karni load`).
- Save migrations and run checks go in `<app>/game.py` (`@hooks.save_migration`,
  `@hooks.run_check`). React to the game with its family events (`game.*`).
- A realtime server is your own service: it verifies the HS256 player token with
  `KARNI_GAME_SERVER_SECRET` and posts signed results to `<game>/multiplayer/results/`.
