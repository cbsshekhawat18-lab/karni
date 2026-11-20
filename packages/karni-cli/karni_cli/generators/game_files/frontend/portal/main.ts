// The game alone, for a game portal: no app around it, the portal's SDK, and the
// game API on the project's domain (KARNI_GAME_API_URL) with the guest's token.
// Build every portal's package from frontend/: npm run game:package
// (docs/game-client.md, "Building for portals").
import { startGame } from "../src/game/play";
import { EMPTY, hasAds, openSession } from "../src/game/session";

const canvas = document.getElementById("game") as HTMLCanvasElement;
const hud = document.getElementById("hud") as HTMLElement;
const ad = document.getElementById("ad") as HTMLButtonElement;

const session = await openSession();
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
