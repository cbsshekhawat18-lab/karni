# __GAME_TITLE__

The game of this project, on [@karni/game](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-game/ui):
its own npm package, served by the project at `/play/__GAME_SLUG__/`. Its server
side is karni-game in the Django project around it: the game is declared in
`content/game.yaml`, and its server hooks are in `games/game.py`.

| Path | What |
|---|---|
| `src/rules/` | the rules: plain functions of a seed and the player's inputs, with no page |
| `src/play.ts` | the canvas, the loop and the input |
| `src/session.ts` | the portal, the data client, and what a finished run reports |
| `src/main.ts`, `index.html` | the page |
| `tests/` | the tests of the rules, headless |

```sh
npm install        # Node 20.19+ and npm 10.8+. Commit the package-lock.json it writes.
npm run dev        # http://localhost:5174/play/__GAME_SLUG__/, the game API proxied to Django
npm test           # the rules, headless
npm run build      # dist/, which the project serves at /play/__GAME_SLUG__/
npm run package    # one package per game portal in dist-portals/, checked and zipped
```

The game API is on the page's own origin when the project serves the game. A
portal package calls the API named by `KARNI_GAME_API_URL` when the build has
it, and plays on the device without it.

The first `npm install` writes `package-lock.json`: commit it, and the
production build installs exactly that (`npm ci`). Without a lock, npm before
11.6 can stop with `Cannot read properties of null (reading 'edgesOut')` while
it resolves Vite's optional peers. Run that first install with npm 11.6 or
later then (`npx --yes npm@11 install`).
