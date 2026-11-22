// The game's page: the canvas, a status line and the ad button, on @karni/game.
// The project serves its build at /play/__GAME_SLUG__/, where the game API is on the
// same origin. A portal package (npm run package) calls the API named by
// KARNI_GAME_API_URL, or plays on the device without it (docs/game-client.md).
import { portalName } from "virtual:karni-game/portal";
import { startGame } from "./play";
import { EMPTY, hasAds, openSession } from "./session";

const canvas = document.getElementById("game") as HTMLCanvasElement;
const hud = document.getElementById("hud") as HTMLElement;
const ad = document.getElementById("ad") as HTMLButtonElement;

const session = await openSession(portalName === "web" ? "same-origin" : undefined);
let last = EMPTY;
const show = async (text: string): Promise<void> => {
    last = await session.snapshot(last);
    const coins = last.wallet?.balances.find((balance) => balance.currency === "coins")?.balance ?? 0;
    hud.textContent = `${text} Best: ${last.progress.best}. Coins: ${coins}.`;
    hud.dataset.best = String(last.progress.best);
    hud.dataset.coins = String(coins);
    hud.dataset.online = last.online ? "yes" : "no";
};

startGame(canvas, {
    portal: session.portal,
    hat: session.hat,
    onScreen: (screen) => {
        hud.dataset.screen = screen;
    },
    onRunEnd: (run) => void session.finishRun(run).then(() => show(`Run over: ${run.score} points.`)),
});
ad.hidden = !hasAds;
ad.addEventListener("click", () => {
    ad.blur();
    void session.watchAd().then((result) => show(result.status === "granted" ? "Coins for the ad." : "No coins this time."));
});
session.portal.loadingFinished();
await show("Tap or press Space to play.");
