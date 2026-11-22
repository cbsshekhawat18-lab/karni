// The trail cosmetics: what the runner leaves behind it. The comet keeps the runner's last
// positions and draws a tail through them, the sparks are particles of @karni/game/draw.
import type { Emitter, Painter, Particles } from "@karni/game/draw";
import { COSMETICS } from "../palette";

const POINTS = 26;

export interface Trail {
    /** Remember where the runner is (each frame while running). */
    follow(x: number, y: number, dt: number): void;
    clear(): void;
    draw(g: Painter): void;
    /** The trail worn now: an item key, or null for none. */
    wear(item: string | null): void;
}

export function createTrail(particles: Particles): Trail {
    const xs = new Float64Array(POINTS);
    const ys = new Float64Array(POINTS);
    let count = 0;
    let head = 0;
    let worn: string | null = null;
    let spark: Emitter | null = null;
    let sparkWait = 0;
    return {
        follow(x, y, dt) {
            head = (head + 1) % POINTS;
            xs[head] = x;
            ys[head] = y;
            count = Math.min(POINTS, count + 1);
            if (spark) {
                sparkWait -= dt;
                if (sparkWait <= 0) {
                    spark.burst(x, y, 2);
                    sparkWait = 0.03;
                }
            }
        },
        clear() {
            count = 0;
        },
        draw(g) {
            if (worn !== "comet-trail" || count < 3) return;
            const [inner = "#cc79a7", outer = "#e69f00"] = COSMETICS[worn]?.colors ?? [];
            for (let i = 1; i < count; i += 1) {
                const a = (head - i + 1 + POINTS) % POINTS;
                const b = (head - i + POINTS) % POINTS;
                const fade = 1 - i / count;
                g.alpha = fade * 0.8;
                g.line(xs[a] as number, ys[a] as number, xs[b] as number, ys[b] as number, outer, 8 * fade + 1);
                g.alpha = fade;
                g.line(xs[a] as number, ys[a] as number, xs[b] as number, ys[b] as number, inner, 4 * fade + 1);
            }
            g.alpha = 1;
        },
        wear(item) {
            worn = item;
            const colors = item ? COSMETICS[item]?.colors : undefined;
            spark =
                item === "spark-trail" && colors
                    ? particles.emitter({
                          speed: [10, 40],
                          angle: [Math.PI * 0.8, Math.PI * 1.2],
                          life: [0.25, 0.45],
                          size: [2, 3],
                          endSize: 0,
                          colors,
                          blend: "lighter",
                      })
                    : null;
        },
    };
}
