// The game on its canvas: the loop, the input and the drawing, on @karni/game's
// plain-canvas helpers. The rules are in ./rules. Space, the up arrow or a tap
// starts a run and jumps.
import {
    POINTER,
    createInput,
    createLoop,
    createView,
    linkPortal,
    pauseOnHidden,
    type Portal,
} from "@karni/game";
import { WORLD, createRun, hopperAt, runScore, stepRun, type Run } from "./rules";

export type Screen = "title" | "play" | "over";

/** A finished run: what the server is told. */
export interface RunResult {
    board: string;
    seed: number;
    score: number;
    coins: number;
    inputs: [number, string][];
    durationMs: number;
}

export interface PlayOptions {
    portal: Portal;
    onRunEnd(result: RunResult): void;
    onScreen?(screen: Screen): void;
    /** The hat the hopper wears (the item equipped in the hat slot), or null. */
    hat?(): string | null;
}

export interface Playing {
    /** Start a run now: a random seed on the high board, or the daily seed on the daily board. */
    play(seed?: number, board?: string): void;
    stop(): void;
}

const COLORS = { sky: "#14202c", block: "#4f8a5b", coin: "#f2c94c", hopper: "#e8eef2", hat: "#d64545" };

export function startGame(canvas: HTMLCanvasElement, options: PlayOptions): Playing {
    const context = canvas.getContext("2d");
    const view = createView({ canvas, width: WORLD.width, height: WORLD.height });
    const input = createInput({
        target: canvas,
        view,
        bindings: { jump: ["Space", "ArrowUp", "KeyW", POINTER] },
    });
    let screen: Screen = "title";
    let run: Run = createRun(1);
    let board = "high";
    let startedAt = 0;
    const show = (next: Screen): void => {
        screen = next;
        canvas.dataset.screen = next;
        options.onScreen?.(next);
    };
    show("title");

    const play = (seed = Math.floor(Math.random() * 2 ** 31), on = "high"): void => {
        run = createRun(seed);
        board = on;
        startedAt = performance.now();
        options.portal.gameplayStart();
        show("play");
    };

    const draw = (): void => {
        if (context === null) return;
        context.setTransform(1, 0, 0, 1, 0, 0);
        context.fillStyle = "#000";
        context.fillRect(0, 0, canvas.width, canvas.height);
        view.apply(context);
        // Only the world is drawn: a hopper falling into a gap never shows in the letterbox.
        context.save();
        context.beginPath();
        context.rect(0, 0, WORLD.width, WORLD.height);
        context.clip();
        context.fillStyle = COLORS.sky;
        context.fillRect(0, 0, WORLD.width, WORLD.height);
        const left = run.distance;
        context.fillStyle = COLORS.block;
        for (const block of run.blocks) {
            if (block.x + block.width < left || block.x > left + WORLD.width) continue;
            context.fillRect(block.x - left, WORLD.floor, block.width, WORLD.height - WORLD.floor);
        }
        context.fillStyle = COLORS.coin;
        for (const coin of run.coins) {
            if (coin.taken || coin.x < left || coin.x > left + WORLD.width) continue;
            context.beginPath();
            context.arc(coin.x - left, WORLD.floor - 10 - coin.y, 6, 0, Math.PI * 2);
            context.fill();
        }
        const top = WORLD.floor - 20 - run.y;
        context.fillStyle = COLORS.hopper;
        context.fillRect(hopperAt(run) - left - 8, top, 16, 20);
        if (options.hat?.()) {
            context.fillStyle = COLORS.hat;
            context.fillRect(hopperAt(run) - left - 9, top - 6, 18, 6);
        }
        context.fillStyle = COLORS.hopper;
        context.font = "14px sans-serif";
        const text = screen === "play" ? String(runScore(run)) : screen === "over" ? "Tap or press Space to play again" : "Tap or press Space to start";
        context.fillText(text, 12, 22);
        context.restore();
    };

    const loop = createLoop({
        step: WORLD.step,
        update: () => {
            const jump = input.pressed("jump");
            if (screen !== "play") {
                if (jump) play();
                return;
            }
            stepRun(run, jump);
            if (!run.over) return;
            options.portal.gameplayStop();
            show("over");
            options.onRunEnd({
                board,
                seed: run.seed,
                score: runScore(run),
                coins: run.collected,
                inputs: run.inputs,
                durationMs: Math.round(performance.now() - startedAt),
            });
        },
        render: draw,
        afterFrame: () => input.endFrame(),
    });
    const unpause = pauseOnHidden([loop]);
    const unlink = linkPortal(options.portal, { loop, input });
    loop.start();
    return {
        play,
        stop() {
            loop.stop();
            unpause();
            unlink();
            input.destroy();
            view.destroy();
        },
    };
}
