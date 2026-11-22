// The game's session with the server: the portal, the player and the data client of
// @karni/game, the save slots, the daily seed, the wallet and the shop, and what a finished
// run reports. The server decides every reward, balance and price: the client only reports
// what happened (a score with its run, counters) and asks (docs/game.md).
import {
    createGameClient,
    createPortal,
    createStorage,
    type AdRewardResult,
    type BoardEntry,
    type DailyState,
    type GameClient,
    type Portal,
    type RunRecord,
    type ShopItem,
    type WalletResponse,
} from "@karni/game";
import { createPortalAdapter, gameApiUrl, portalName } from "virtual:karni-game/portal";
import { BOARDS, COUNTERS, GAME, LOCAL, REWARDS, SAVE_VERSION, SLOTS, type Mode } from "./game";

/** The "progress" slot: the player's bests and totals. */
export interface Progress {
    best: number;
    runs: number;
    coins: number;
}

/** The "daily" slot: today's best on the day's seed. */
export interface DailyBest {
    date: string;
    best: number;
    tries: number;
}

/** A finished run, as the game reports it. A run that went on after a continue reports again. */
export interface RunReport {
    mode: Mode;
    score: number;
    /** Coins picked up since the last report of this run. */
    coins: number;
    run: RunRecord;
    /** This report extends one already sent (after a continue): it is not a new run. */
    continued: boolean;
}

export interface Session {
    readonly portal: Portal;
    readonly client: GameClient;
    /** A server keeps the boards, the wallet and the saves (false: this device only). */
    readonly hasServer: boolean;
    progress: Progress;
    daily: DailyState | null;
    dailyBest: DailyBest | null;
    wallet: WalletResponse | null;
    coins(): number;
    /** The item worn in a slot ("trail", "hat"), or null. */
    wearing(slot: string): string | null;
    refresh(): Promise<void>;
    shop(): Promise<ShopItem[]>;
    buy(item: string): Promise<void>;
    equip(item: string): Promise<void>;
    checkIn(): Promise<number>;
    adCoins(): Promise<AdRewardResult>;
    /** A rewarded ad for a continue: true when the server granted it. */
    continueRun(): Promise<boolean>;
    /** Send the score and the counters, keep the saves, and read the top of its board. */
    finish(report: RunReport): Promise<readonly BoardEntry[]>;
    board(mode: Mode): Promise<readonly BoardEntry[]>;
}

const settle = async <T>(work: Promise<T>, fallback: T): Promise<T> => {
    try {
        return await work;
    } catch {
        return fallback;
    }
};

/** Each step of the start, for the loading scene's bar. */
export type BootStep = (done: number, total: number) => void;

/**
 * Start the portal, the storage (after the portal, so a portal's data module is read) and the
 * data client. The project serves the web build at /play/<slug>/, so its game API is on the
 * page's own origin. A portal build calls the API that KARNI_GAME_API_URL names, or plays on
 * the device without one.
 */
export async function openSession(onStep: BootStep = () => undefined): Promise<Session> {
    const total = 5;
    const portal = createPortal(createPortalAdapter());
    await portal.init();
    onStep(1, total);
    const storage = createStorage({ namespace: GAME, portal: portal.storage() });
    const sameOrigin = portalName === "web" || portalName === "fake";
    const server = gameApiUrl ? { baseUrl: gameApiUrl } : sameOrigin ? {} : undefined;
    const client = createGameClient({ game: GAME, storage, server, local: LOCAL });
    await client.boot();
    onStep(2, total);
    await client.signInGuest();
    onStep(3, total);
    const saved = await settle(client.saves.load<Progress>(SLOTS.progress), null);
    const daily = await settle(client.daily(), null);
    const savedDaily = await settle(client.saves.load<DailyBest>(SLOTS.daily), null);
    onStep(4, total);

    const session: Session = {
        portal,
        client,
        hasServer: client.hasServer,
        progress: { best: 0, runs: 0, coins: 0, ...saved?.data },
        daily,
        dailyBest: savedDaily && daily && savedDaily.data.date === daily.date ? savedDaily.data : null,
        wallet: null,
        coins: () => session.wallet?.balances.find((b) => b.currency === "coins")?.balance ?? 0,
        wearing: (slot) => session.wallet?.items.find((i) => i.slot === slot && i.equipped)?.item ?? null,
        async refresh() {
            session.wallet = await settle(client.wallet(), session.wallet);
        },
        shop: () => settle(client.shop(), []),
        async buy(item) {
            await client.buy(item);
            await session.refresh();
        },
        async equip(item) {
            await client.equip(item);
            await session.refresh();
        },
        async checkIn() {
            const before = session.coins();
            await settle(client.checkIn(), null);
            await session.refresh();
            return session.coins() - before;
        },
        async adCoins() {
            const result = await client.adReward(REWARDS.adCoins, () => portal.rewarded("coins"));
            await session.refresh();
            return result;
        },
        async continueRun() {
            const result = await client.adReward(REWARDS.continue, () => portal.rewarded("continue"));
            return result.status === "granted" || result.status === "pending";
        },
        async finish(report) {
            const board = BOARDS[report.mode];
            await settle(client.submitScore(board, report.score, { run: report.run }), null);
            const events: { counter: string; amount: number }[] = report.continued
                ? []
                : [{ counter: COUNTERS.runs, amount: 1 }];
            if (report.coins > 0) events.push({ counter: COUNTERS.coins, amount: report.coins });
            if (report.mode === "daily" && !report.continued) events.push({ counter: COUNTERS.daily, amount: 1 });
            if (events.length) await settle(client.progress(events), null);
            // With no server the device's own economy pays for the coins picked up. A server
            // pays only the rewards it declares (achievements, missions, the daily coins).
            if (!client.hasServer && report.coins > 0) client.grant("coins", report.coins, "run");
            const p = session.progress;
            const runs = p.runs + (report.continued ? 0 : 1);
            session.progress = { best: Math.max(p.best, report.score), runs, coins: p.coins + report.coins };
            client.saves.write(SLOTS.progress, session.progress, SAVE_VERSION);
            if (report.mode === "daily" && session.daily) {
                const today = session.dailyBest ?? { date: session.daily.date, best: 0, tries: 0 };
                const tries = today.tries + (report.continued ? 0 : 1);
                session.dailyBest = { ...today, best: Math.max(today.best, report.score), tries };
                client.saves.write(SLOTS.daily, session.dailyBest, SAVE_VERSION);
            }
            client.track("run_end", { mode: report.mode, score: report.score, ms: report.run.duration_ms ?? 0 });
            await session.refresh();
            return session.board(report.mode);
        },
        async board(mode) {
            const period = mode === "daily" ? "daily" : "all";
            const found = await settle(client.leaderboard(BOARDS[mode], { period, limit: 5 }), null);
            return found?.entries ?? [];
        },
    };
    await session.refresh();
    onStep(5, total);
    return session;
}
