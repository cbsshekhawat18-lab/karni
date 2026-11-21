// The game's names in one place: its slug on the server, its boards, save slots, rewards and
// items. The server declares the same rows in content/game.yaml and decides every price and
// reward from there. LOCAL is the same game for a build with no server (a portal package
// without KARNI_GAME_API_URL): it plays on the device, and its coins never reach a server.
import type { LocalGameSetup } from "@karni/game";

export const GAME = "__GAME_SLUG__";
export const TITLE = "__GAME_TITLE__";

export const BOARDS = {
    /** The endless run on a new seed each time. */
    endless: "distance",
    /** Today's run: the server's seed of the day, the same track for every player. */
    daily: "daily",
} as const;
export type Mode = keyof typeof BOARDS;

/** Save slots: what the player did overall, and today's run. Version 1 of both shapes. */
export const SLOTS = { progress: "progress", daily: "daily" } as const;
export const SAVE_VERSION = 1;

export const REWARDS = {
    /** Coins once a day for opening the game. */
    daily: "daily-coins",
    /** Coins for a rewarded ad, a few times a day. */
    adCoins: "ad-coins",
    /** A continue after a fall, for a rewarded ad: the server counts them, three a day. */
    continue: "continue",
} as const;

/** The cosmetics: a trail behind the runner and a hat on it. */
export const ITEMS = {
    sparkTrail: "spark-trail",
    cometTrail: "comet-trail",
    cap: "cap",
    crown: "crown",
} as const;

/** The counters a finished run reports: the server's achievements and missions count them. */
export const COUNTERS = { runs: "runs", coins: "coins_collected", daily: "daily_runs" } as const;

export const LOCAL: LocalGameSetup = {
    boards: {
        [BOARDS.endless]: { title: "Distance", order: "desc", keep: 10 },
        [BOARDS.daily]: { title: "Daily run", order: "desc", keep: 10 },
    },
    currencies: [{ key: "coins", title: "Coins", cap: 99999 }],
    shop: [
        { key: ITEMS.sparkTrail, title: "Spark trail", slot: "trail", price: { currency: "coins", amount: 60 } },
        { key: ITEMS.cometTrail, title: "Comet trail", slot: "trail", price: { currency: "coins", amount: 150 } },
        { key: ITEMS.cap, title: "Cap", slot: "hat", price: { currency: "coins", amount: 40 } },
        { key: ITEMS.crown, title: "Crown", slot: "hat", price: { currency: "coins", amount: 120 } },
    ],
    rewards: [
        { key: REWARDS.daily, title: "Daily coins", kind: "daily", currency: "coins", amount: 20 },
        { key: REWARDS.adCoins, title: "Coins for an ad", kind: "ad", currency: "coins", amount: 25, perDay: 3 },
        { key: REWARDS.continue, title: "A continue", kind: "ad", currency: "coins", amount: 0, perDay: 3 },
    ],
    achievements: [
        { key: "first-run", title: "First run", counter: COUNTERS.runs, goal: 1 },
        { key: "collector", title: "Collector", counter: COUNTERS.coins, goal: 100 },
    ],
};
