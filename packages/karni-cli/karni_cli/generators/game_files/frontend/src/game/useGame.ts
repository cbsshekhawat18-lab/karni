// The game inside the app, as a React hook: it opens the session on the app's own
// API client, starts the canvas, refreshes what the page shows after each run and
// each action, and keeps the guest's progress when the player signs in.
import { useKarniClient } from "@karni/ui";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { startGame, type Playing, type Screen } from "./play";
import { EMPTY, openSession, type Session, type Snapshot } from "./session";

export interface GameState extends Snapshot {
    ready: boolean;
    screen: Screen;
    /** The last thing that happened, for the status line. */
    notice: string;
}

export interface GameActions {
    playDaily(): void;
    checkIn(): Promise<void>;
    watchAd(): Promise<void>;
    buy(item: string): Promise<void>;
    equip(item: string): Promise<void>;
}

const wording = (error: unknown): string =>
    error instanceof Error ? error.message : "Something went wrong. Try again.";

export function useGame(
    canvas: RefObject<HTMLCanvasElement | null>,
    signedIn: boolean,
): GameState & GameActions {
    const transport = useKarniClient();
    const account = useRef(signedIn);
    account.current = signedIn;
    const session = useRef<Session | null>(null);
    const playing = useRef<Playing | null>(null);
    const latest = useRef<Snapshot>(EMPTY);
    const [state, setState] = useState<GameState>({ ...EMPTY, ready: false, screen: "title", notice: "" });

    const refresh = useCallback(async (notice?: string): Promise<void> => {
        const open = session.current;
        if (open === null) return;
        const snapshot = await open.snapshot(latest.current);
        latest.current = snapshot;
        setState((current) => ({ ...current, ...snapshot, notice: notice ?? current.notice }));
    }, []);

    useEffect(() => {
        const element = canvas.current;
        if (element === null) return undefined;
        let live = true;
        void openSession({ transport, signedIn: () => account.current }).then(async (open) => {
            if (!live) return open.destroy();
            session.current = open;
            const sync = (): void => void refresh();
            open.client.on("synced", sync);
            open.client.on("online", sync);
            playing.current = startGame(element, {
                portal: open.portal,
                hat: open.hat,
                onScreen: (screen) => setState((current) => ({ ...current, screen })),
                onRunEnd: (run) => void open.finishRun(run).then(() => refresh(`Run over: ${run.score} points.`)),
            });
            open.portal.loadingFinished();
            await refresh();
            setState((current) => ({ ...current, ready: true }));
        });
        return () => {
            live = false;
            playing.current?.stop();
            session.current?.destroy();
            session.current = null;
        };
    }, [canvas, transport, refresh]);

    useEffect(() => {
        const open = session.current;
        if (!signedIn || open === null) return;
        void open
            .keepProgress()
            .then((kept) => refresh(kept ? "Your progress is on your account now." : undefined))
            .catch((error: unknown) => refresh(wording(error)));
    }, [signedIn, state.ready, refresh]);

    const act = useCallback(
        async (work: (open: Session) => Promise<string>): Promise<void> => {
            const open = session.current;
            if (open === null) return;
            await refresh(await work(open).catch(wording));
        },
        [refresh],
    );

    return {
        ...state,
        playDaily: () => {
            const daily = state.daily;
            if (daily?.board) playing.current?.play(daily.seed, daily.board);
        },
        checkIn: () => act(async (open) => (await open.checkIn(), "Checked in for today.")),
        watchAd: () =>
            act(async (open) => {
                const result = await open.watchAd();
                if (result.status === "granted") return `+${result.granted.amount} coins.`;
                if (result.status === "pending") return "The portal confirms the ad: the coins come in a moment.";
                return result.status === "not-watched" ? "The ad did not finish." : "No ad reward now.";
            }),
        buy: (item) => act(async (open) => (await open.buy(item), "Bought.")),
        equip: (item) => act(async (open) => (await open.equip(item), "Equipped.")),
    };
}
