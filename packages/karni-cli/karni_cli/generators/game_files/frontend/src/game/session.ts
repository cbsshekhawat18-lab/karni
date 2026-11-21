// The game's session with the server: the portal, the player and the data client
// of @karni/game, and what a finished run reports. No React here, so every page
// that hosts the game shares it: a page of the app, the game's own page, a portal.
// The server decides every reward, balance and unlock: the client only reports
// what happened and asks (docs/game.md).
import {
    createGameClient,
    createPortal,
    createStorage,
    type Achievement,
    type AdRewardResult,
    type BoardResponse,
    type DailyState,
    type GameClient,
    type Player,
    type Portal,
    type ShopItem,
    type Transport,
    type WalletResponse,
} from "@karni/game";
import { createPortalAdapter, gameApiUrl, portalName } from "virtual:karni-game/portal";
import type { RunResult } from "./play";

export const GAME = "__GAME_SLUG__";
/** The build's portal shows ads: the project's own site and itch.io have no ad SDK. */
export const hasAds = portalName !== "web" && portalName !== "itch";
/** The save the game keeps in its "main" slot, version 1 of its shape. */
export interface Progress {
    best: number;
    runs: number;
}

/** What the page shows. A part the server could not answer keeps its last value. */
export interface Snapshot {
    player: Player | null;
    online: boolean;
    waiting: number;
    progress: Progress;
    wallet: WalletResponse | null;
    shop: ShopItem[];
    board: BoardResponse | null;
    achievements: Achievement[];
    daily: DailyState | null;
}

export const EMPTY: Snapshot = {
    player: null,
    online: false,
    waiting: 0,
    progress: { best: 0, runs: 0 },
    wallet: null,
    shop: [],
    board: null,
    achievements: [],
    daily: null,
};

export interface Session {
    readonly portal: Portal;
    readonly client: GameClient;
    /** The item the player wears in the hat slot, or null. */
    hat(): string | null;
    finishRun(run: RunResult): Promise<void>;
    snapshot(previous: Snapshot): Promise<Snapshot>;
    checkIn(): Promise<void>;
    watchAd(): Promise<AdRewardResult>;
    buy(item: string): Promise<void>;
    equip(item: string): Promise<void>;
    /** After the player signed in: the guest's progress joins the account (POST upgrade/). */
    keepProgress(): Promise<boolean>;
    destroy(): void;
}

/** The project's own API client, for the page inside the app: the calls carry the account. */
export interface AppServer {
    transport: Transport;
    signedIn(): boolean;
}

const settle = async <T>(work: Promise<T>, fallback: T): Promise<T> => {
    try {
        return await work;
    } catch {
        return fallback;
    }
};

/** Offline the client answers this device's own scores: the last shared board stays instead. */
const shared = async (work: Promise<BoardResponse>, last: BoardResponse | null): Promise<BoardResponse | null> => {
    const board = await settle<BoardResponse | null>(work, last);
    return board?.local && last ? last : board;
};

/**
 * Start the portal, make the game's storage after it (so a portal's data
 * module is read) and the data client. A portal build calls the game API on
 * the project's domain (gameApiUrl, KARNI_GAME_API_URL) with the guest's
 * token. Inside the app the calls go through the app's own client.
 * "same-origin": the project serves the page (/play/<slug>/), so the game API
 * is on the page's own origin. Without any of them the game plays on the device.
 */
export async function openSession(app?: AppServer | "same-origin"): Promise<Session> {
    const portal = createPortal(createPortalAdapter());
    await portal.init();
    const storage = createStorage({ namespace: GAME, portal: portal.storage() });
    const server = gameApiUrl
        ? { baseUrl: gameApiUrl }
        : app === "same-origin"
          ? {}
          : app
            ? { transport: app.transport, signedIn: () => app.signedIn(), path: "/api/game/" }
            : undefined;
    const client = createGameClient({ game: GAME, storage, server });
    await client.boot();
    await client.signInGuest();
    let wearing: string | null = null;
    let progress: Progress = { best: 0, runs: 0 };
    const loaded = await settle(client.saves.load<Progress>("main"), null);
    if (loaded) progress = { ...progress, ...loaded.data };

    return {
        portal,
        client,
        hat: () => wearing,
        async finishRun(run) {
            await client.submitScore(run.board, run.score, {
                run: { seed: String(run.seed), inputs: run.inputs, duration_ms: run.durationMs },
            });
            const events = [{ counter: "levels_done", amount: 1 }];
            if (run.coins > 0) events.push({ counter: "coins_collected", amount: run.coins });
            await client.progress(events);
            progress = { best: Math.max(progress.best, run.score), runs: progress.runs + 1 };
            client.saves.write("main", progress, 1);
            client.track("level_done", { level: 1, ms: run.durationMs });
        },
        async snapshot(previous) {
            const wallet = await settle(client.wallet(), previous.wallet);
            wearing = wallet?.items.find((item) => item.slot === "hat" && item.equipped)?.item ?? null;
            return {
                player: client.player,
                online: client.online,
                waiting: client.queue.size,
                progress,
                wallet,
                shop: await settle(client.shop(), previous.shop),
                board: await shared(client.leaderboard("high", { limit: 10 }), previous.board),
                achievements: await settle(client.achievements(), previous.achievements),
                daily: await settle(client.daily(), previous.daily),
            };
        },
        async checkIn() {
            await client.checkIn();
        },
        watchAd: () => client.adReward("ad-coins", () => portal.rewarded("coins")),
        async buy(item) {
            await client.buy(item);
        },
        async equip(item) {
            await client.equip(item);
        },
        async keepProgress() {
            if (!client.player?.guest || client.player.local) return false;
            await client.upgrade();
            return true;
        },
        destroy: () => client.destroy(),
    };
}
