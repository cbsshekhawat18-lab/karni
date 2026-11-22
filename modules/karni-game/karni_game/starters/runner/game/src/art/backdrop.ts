// The sky behind the track: a gradient and a sun, two bands of hills and two of clouds, each
// a path made once and repeated across what its parallax layer shows. Decoration only: none
// of it is in the rules, so it may use Math.sin and anything else.
import type { Painter } from "@karni/game/draw";
import type { Palette } from "../palette";
import { WORLD } from "../rules";

/** How wide one repeat of a band is, in its layer's units. */
const TILE = 960;

function hills(base: number, amplitude: number, waves: readonly [number, number][]): Path2D {
    const path = new Path2D();
    path.moveTo(0, WORLD.height);
    for (let x = 0; x <= TILE; x += 8) {
        let y = base;
        for (const [length, share] of waves) y -= Math.sin((x / TILE) * Math.PI * 2 * length) * amplitude * share;
        path.lineTo(x, y);
    }
    path.lineTo(TILE, WORLD.height);
    path.closePath();
    return path;
}

function clouds(count: number, y: number, size: number, seed: number): Path2D {
    const path = new Path2D();
    for (let i = 0; i < count; i += 1) {
        const cx = ((i + 0.5) / count) * TILE + Math.sin(i * 12.9898 + seed) * 60;
        const cy = y + Math.sin(i * 78.233 + seed) * 18;
        for (let puff = 0; puff < 5; puff += 1) {
            const r = size * (0.55 + 0.45 * Math.abs(Math.sin(i * 3 + puff * 1.7 + seed)));
            path.moveTo(cx + (puff - 2) * size * 0.7 + r, cy);
            path.arc(cx + (puff - 2) * size * 0.7, cy - Math.abs(puff - 2) * -size * 0.12, r, 0, Math.PI * 2);
        }
    }
    return path;
}

export interface Backdrop {
    sky(g: Painter): void;
    far(g: Painter): void;
    mid(g: Painter): void;
    front(g: Painter): void;
    setPalette(palette: Palette): void;
}

/** Repeat `path` across the area the layer shows. */
function tiled(g: Painter, path: Path2D, fill: string, alpha = 1): void {
    const context = g.ctx;
    context.save();
    context.globalAlpha *= alpha;
    context.fillStyle = fill;
    const first = Math.floor(g.left / TILE) * TILE;
    for (let x = first; x < g.left + g.width; x += TILE) {
        context.translate(x, 0);
        context.fill(path);
        context.translate(-x, 0);
    }
    context.restore();
}

export function createBackdrop(context: CanvasRenderingContext2D, start: Palette): Backdrop {
    const farHills = hills(170, 40, [[2, 0.6], [5, 0.3], [11, 0.1]]);
    const nearHills = hills(205, 30, [[3, 0.5], [7, 0.35], [13, 0.15]]);
    const midClouds = clouds(5, 70, 18, 1);
    const frontClouds = clouds(9, WORLD.height + 6, 26, 4);
    let palette = start;
    let gradient: CanvasGradient | null = null;
    const sky = (): CanvasGradient => {
        if (!gradient) {
            gradient = context.createLinearGradient(0, 0, 0, WORLD.height);
            gradient.addColorStop(0, palette.skyTop);
            gradient.addColorStop(1, palette.skyBottom);
        }
        return gradient;
    };
    return {
        sky(g) {
            g.rect(0, 0, WORLD.width, WORLD.height, sky());
            for (let i = 0; i < 28; i += 1) {
                const x = (i * 137.5) % WORLD.width;
                const y = (i * 61.3) % 120;
                g.alpha = 0.35 + 0.3 * Math.abs(Math.sin(i * 1.7));
                g.rect(x, y, 1.5, 1.5, palette.star);
            }
            g.alpha = 0.9;
            g.circle(370, 62, 26, palette.sun);
        },
        far: (g) => tiled(g, farHills, palette.farHills),
        mid(g) {
            tiled(g, midClouds, palette.cloud, 0.35);
            tiled(g, nearHills, palette.nearHills);
        },
        front: (g) => tiled(g, frontClouds, palette.cloud, 0.92),
        setPalette(next) {
            palette = next;
            gradient = null;
        },
    };
}
