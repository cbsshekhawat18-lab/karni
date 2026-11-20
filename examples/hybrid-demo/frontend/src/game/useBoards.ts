// The game's boards for the leaderboard page: every member's best, and today's deal.
import type { BoardResponse } from "@karni/game";
import { useEffect, useState } from "react";
import { useGameClient } from "./client";

export function useBoards() {
    const client = useGameClient();
    const [boards, setBoards] = useState<{ best: BoardResponse; daily: BoardResponse } | null>(null);
    const [error, setError] = useState<unknown>(null);
    useEffect(() => {
        Promise.all([
            client.leaderboard("best", { period: "all", limit: 20 }),
            client.leaderboard("daily", { period: "daily", limit: 20 }),
        ])
            .then(([best, daily]) => setBoards({ best, daily }))
            .catch(setError);
    }, [client]);
    return { boards, error };
}
