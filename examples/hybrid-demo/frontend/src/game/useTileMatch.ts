// A member's game of Tile Match: a deal to play, the daily deal from the server's seed,
// and what a clear reports (the score with its run, the progress that unlocks achievements).
import { httpError, type Achievement, type DailyState } from "@karni/game";
import { useCallback, useEffect, useState } from "react";
import { useGameClient } from "./client";
import { cleared, deal, score, turn, type Deal } from "./tiles";

const randomSeed = (): number => Math.floor(Math.random() * 2 ** 31);

const explain = (error: unknown): string =>
    httpError(error)?.code === "GAME004"
        ? "Verify your email address to put your clears on the board."
        : "The game server cannot be reached: your clears wait and are sent later.";

export function useTileMatch() {
    const client = useGameClient();
    const [current, setCurrent] = useState<Deal>(() => deal(randomSeed()));
    const [board, setBoard] = useState("best");
    const [notice, setNotice] = useState("Turn two tiles. A pair stays open.");
    const [achievements, setAchievements] = useState<Achievement[]>([]);
    const [daily, setDaily] = useState<DailyState | null>(null);
    const [handle, setHandle] = useState("");

    const refresh = useCallback(async (): Promise<void> => {
        setAchievements(await client.achievements());
    }, [client]);

    useEffect(() => {
        void client
            .boot()
            .then(async () => {
                setDaily(await client.daily());
                setHandle((await client.signInGuest()).handle);
                await refresh();
            })
            .catch((error: unknown) => setNotice(explain(error)));
    }, [client, refresh]);

    const finish = async (done: Deal, on: string): Promise<void> => {
        try {
            const run = { seed: String(done.seed), inputs: done.log };
            const sent = await client.submitScore(on, score(done), { run });
            const progress = await client.progress([{ counter: "deals_cleared", amount: 1 }]);
            const unlocked = progress.server?.unlocked.map((row) => row.title) ?? [];
            const rank = sent.server?.best.all?.rank ?? sent.server?.best.daily?.rank;
            setNotice(
                `Cleared in ${done.moves} moves: ${score(done)} points${rank ? `, rank ${rank}` : ""}.` +
                    (unlocked.length ? ` Unlocked: ${unlocked.join(", ")}.` : ""),
            );
            await refresh();
        } catch (error) {
            setNotice(explain(error));
        }
    };

    return {
        current,
        board,
        notice,
        achievements,
        daily,
        turn: (index: number) => {
            const next = turn(current, index);
            setCurrent(next);
            if (cleared(next) && !cleared(current)) void finish(next, board);
        },
        handle,
        rename: async (name: string) => {
            try {
                setHandle((await client.setHandle(name)).handle);
            } catch (error) {
                setNotice(explain(error));
            }
        },
        newDeal: () => {
            setBoard("best");
            setNotice("A new deal.");
            setCurrent(deal(randomSeed()));
        },
        dailyDeal: () => {
            if (daily === null || daily.board === null) return;
            setBoard(daily.board);
            setNotice("Today's deal: the same tiles for every member.");
            setCurrent(deal(daily.seed));
        },
    };
}
