// The runner, its hats and the coin, painted once in code on a canvas and cut into sprites
// with @karni/game/draw: a sprite is a region of any image, a canvas painted in code
// included. Painted at three times the game's size, so they stay sharp on a phone.
import { createSprite, defineClips, sheetFrames, type Clip, type Sprite } from "@karni/game/draw";
import type { Palette } from "../palette";
import { COSMETICS } from "../palette";

const SCALE = 3;
/** The runner's frame, in game units: its box is 14 by 18, drawn with a little room. */
const FRAME = { w: 16, h: 20 };

export interface Sprites {
    clips: Record<"run" | "rise" | "fall", Clip>;
    coin: Sprite;
    hats: Record<string, Sprite>;
}

function canvas(w: number, h: number): CanvasRenderingContext2D {
    const element = document.createElement("canvas");
    element.width = w * SCALE;
    element.height = h * SCALE;
    const context = element.getContext("2d");
    if (!context) throw new Error("This browser cannot draw on a canvas.");
    context.scale(SCALE, SCALE);
    return context;
}

function roundRect(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
}

/** One frame of the runner at `ox`: a round body, an eye looking ahead, a scarf and two legs. */
function paintRunner(c: CanvasRenderingContext2D, ox: number, legs: [number, number], p: Palette): void {
    const x = ox + 1;
    c.fillStyle = p.eye;
    c.fillRect(x + 3 + legs[0], 15, 3, 4);
    c.fillRect(x + 8 + legs[1], 15, 3, 4);
    roundRect(c, x, 2, 14, 14, 5);
    c.fillStyle = p.runner;
    c.fill();
    if (p.outline) {
        c.lineWidth = 1.2;
        c.strokeStyle = p.outline;
        c.stroke();
    }
    c.fillStyle = p.runnerShade;
    c.fillRect(x + 2, 12, 10, 3);
    c.fillStyle = "#ffffff";
    c.fillRect(x + 8, 5, 4, 4);
    c.fillStyle = p.eye;
    c.fillRect(x + 10, 6, 2, 2);
    c.fillStyle = "#56b4e9";
    c.fillRect(x - 1, 9, 6, 2);
}

function paintCoin(c: CanvasRenderingContext2D, p: Palette): void {
    c.beginPath();
    c.arc(6, 6, 5.5, 0, Math.PI * 2);
    c.fillStyle = p.coin;
    c.fill();
    c.lineWidth = 1;
    c.strokeStyle = p.outline ?? "#a88f00";
    c.stroke();
    c.fillStyle = p.coinShine;
    c.fillRect(4, 3, 2, 5);
}

function paintHat(c: CanvasRenderingContext2D, key: string): void {
    const [main = "#0072b2", gem = "#d55e00"] = COSMETICS[key]?.colors ?? [];
    c.fillStyle = main;
    if (key === "crown") {
        c.beginPath();
        c.moveTo(1, 8);
        for (const [px, py] of [[1, 2], [4, 5], [7, 0], [10, 5], [13, 2], [13, 8]] as const) c.lineTo(px, py);
        c.closePath();
        c.fill();
        c.fillStyle = gem;
        c.fillRect(6, 5, 2, 2);
    } else {
        c.beginPath();
        c.arc(7, 7, 6, Math.PI, 0);
        c.fill();
        c.fillRect(7, 5, 8, 2);
    }
}

/** Paint every sprite for a palette. Call it again when the palette changes. */
export function paintSprites(palette: Palette): Sprites {
    const sheet = canvas(FRAME.w * 5, FRAME.h);
    const poses: [number, number][] = [[0, 0], [1, -1], [0, 0], [-1, 1], [0, -2]];
    poses.forEach((legs, frame) => paintRunner(sheet, frame * FRAME.w, legs, palette));
    const frames = sheetFrames(sheet.canvas, FRAME.w * SCALE, FRAME.h * SCALE, {
        anchor: [0, 0],
        scale: 1 / SCALE,
    });
    const clips = defineClips(frames, {
        run: { frames: [0, 1, 2, 3], fps: 14 },
        rise: { frames: [4], fps: 1 },
        fall: { frames: [2], fps: 1 },
    });
    const coinCanvas = canvas(12, 12);
    paintCoin(coinCanvas, palette);
    const hats: Record<string, Sprite> = {};
    for (const key of ["cap", "crown"]) {
        const hat = canvas(16, 9);
        paintHat(hat, key);
        hats[key] = createSprite(hat.canvas, { anchor: [0.5, 1], scale: 1 / SCALE });
    }
    return { clips, coin: createSprite(coinCanvas.canvas, { anchor: [0.5, 0.5], scale: 1 / SCALE }), hats };
}
