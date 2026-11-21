// A run from start to end: the recorder over the rules, the endless and daily modes, the
// end of a run reported to the server, and the continue. The scenes ask for these; the rules
// stay in src/rules and never see any of it.
import type { BoardEntry } from "@karni/game";
import { createRecorder, toRunRecord, type Recorder } from "@karni/game/sim";
import type { Art } from "./art/art";
import type { Mode } from "./game";
import { distance, runnerSim, type RunEvent, type RunState, type RunnerInput } from "./rules";
import type { Sfx } from "@karni/game/sfx";
import type { Session } from "./session";
import { playEvent } from "./sound";

export type Screen = "loading" | "title" | "play" | "over";

/** What the game-over panel shows. */
export interface RunResult {
    mode: Mode;
    score: number;
    distance: number;
    coins: number;
    best: number;
    /** A continue is open: the run has one left and an ad can play. */
    canContinue: boolean;
    board: Promise<readonly BoardEntry[]>;
}

export interface RunControl {
    /** The run being played, recorded: what the sim loop steps. */
    readonly recorder: Recorder<RunState, RunnerInput, RunEvent>;
    readonly state: RunState;
    readonly mode: Mode;
    readonly screen: Screen;
    readonly session: Session | null;
    /** Make the session the runs report to, once it is open. */
    useSession(session: Session): void;
    /** A new run: the endless one on a new seed, or today's on the server's seed. */
    begin(mode: Mode): void;
    /** The player's input for one tick, read by the sim loop. */
    input(): RunnerInput;
    events(events: readonly RunEvent[]): void;
    /** Ask for a continue: a rewarded ad, and then the server must grant it. */
    continueRun(): Promise<boolean>;
    show(screen: Screen): void;
    readonly last: RunResult | null;
}

export interface RunOptions {
    art: Art;
    sfx: Sfx;
    /** Read the jump of this tick from the input layer. */
    jumped(): boolean;
    /** The screen changed: the scenes follow, the page's HUD says it. */
    onScreen(screen: Screen): void;
    /** A run ended: show its result. */
    onOver(result: RunResult): void;
}

export function createRunControl(options: RunOptions): RunControl {
    const { art, sfx } = options;
    const newRun = (seed: number): Recorder<RunState, RunnerInput, RunEvent> => {
        const run = createRecorder(runnerSim, { seed });
        // The sim steps its state in place, so the camera follows the same object all run.
        art.follow(run.sim.state);
        return run;
    };
    let recorder = newRun(1);
    let mode: Mode = "endless";
    let screen: Screen = "loading";
    let session: Session | null = null;
    let reviveNext = false;
    let last: RunResult | null = null;
    /** Coins of this run already reported, and whether it was reported once (before a continue). */
    let reported = { coins: 0, once: false };

    const finish = (): void => {
        const value = recorder.sim.score;
        const state = recorder.sim.state;
        const best = Math.max(session?.progress.best ?? 0, value);
        const recording = recorder.finish();
        const report = {
            mode,
            score: value,
            coins: state.coins - reported.coins,
            run: toRunRecord(recording),
            continued: reported.once,
        };
        reported = { coins: state.coins, once: true };
        const board = session ? session.finish(report) : Promise.resolve([]);
        const canContinue = state.continues < 1 && session !== null && session.portal.canShowRewarded();
        last = { mode, score: value, distance: distance(state), coins: state.coins, best, canContinue, board };
        control.show("over");
        options.onOver(last);
        void session?.portal.interstitial("game-over");
    };

    const control: RunControl = {
        get recorder() {
            return recorder;
        },
        get state() {
            return recorder.sim.state;
        },
        get mode() {
            return mode;
        },
        get screen() {
            return screen;
        },
        get session() {
            return session;
        },
        get last() {
            return last;
        },
        useSession(opened) {
            session = opened;
            art.wearTrail(opened.wearing("trail"));
        },
        begin(next) {
            mode = next;
            // The daily run is on the server's seed of the day (the device's, offline, for
            // practice). The page may use Math.random: only src/rules may not.
            const daily = session?.daily;
            const seed = next === "daily" && daily ? daily.seed : Math.floor(Math.random() * 2 ** 31);
            recorder = newRun(seed);
            reported = { coins: 0, once: false };
            art.wearTrail(session?.wearing("trail") ?? null);
            sfx.music("music", { fade: 1, volume: 0.6 });
            control.show("play");
        },
        input() {
            const step = { jump: options.jumped(), revive: reviveNext };
            reviveNext = false;
            return step;
        },
        events(list) {
            const { runner } = recorder.sim.state;
            for (const event of list) {
                playEvent(sfx, event);
                if (event === "coin") art.coin(runner.x + runner.w, runner.y);
                if (event === "land") art.land(runner.x + runner.w / 2, runner.y + runner.h);
                if (event === "spike" || event === "fall") {
                    art.crash(runner.x + runner.w / 2, Math.min(runner.y, 260));
                    finish();
                }
            }
        },
        async continueRun() {
            if (!session || screen !== "over" || recorder.sim.state.continues >= 1) return false;
            if (!(await session.continueRun())) return false;
            // The recording goes on: the continue is an input of the same run.
            reviveNext = true;
            control.show("play");
            return true;
        },
        show(next) {
            screen = next;
            if (next === "play") session?.portal.gameplayStart();
            else session?.portal.gameplayStop();
            options.onScreen(next);
        },
    };
    return control;
}
