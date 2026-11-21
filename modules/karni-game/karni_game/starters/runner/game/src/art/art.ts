// The game's drawing on @karni/game/draw: layers in order (the sky, two parallax bands, the
// track, the effects, a cloud band in front and the HUD), a camera that keeps the runner a
// quarter of the way across, sprites painted in code, particles and the trail.
import type { View } from "@karni/game";
import {
    REDUCED_MOTION,
    createAnimator,
    createCamera,
    createParticles,
    createRenderer,
    textStyle,
    type Painter,
} from "@karni/game/draw";
import { PALETTE, SAFE_PALETTE, type Palette } from "../palette";
import { WORLD, distance, type RunState } from "../rules";
import { createBackdrop } from "./backdrop";
import { paintSprites, type Sprites } from "./sprites";
import { createTrail } from "./trail";

/** What the drawing reads from the game each frame. */
export interface ArtSource {
    state(): RunState;
    /** The run is on screen and moving (the trail follows only then). */
    running(): boolean;
    best(): number;
    /** "Daily" during the daily run, else "". */
    label(): string;
    hat(): string | null;
}

export function createArt(canvas: HTMLCanvasElement, view: View, source: ArtSource) {
    const camera = createCamera({
        view,
        offset: { x: -WORLD.width * 0.22, y: 0 },
        bounds: { x: -100, y: 0, w: Infinity, h: WORLD.height },
        smoothing: 0,
    });
    const renderer = createRenderer({
        canvas,
        view,
        camera,
        background: "#0b1d33",
        layers: [
            { name: "sky", screen: true },
            { name: "far", parallax: 0.12 },
            { name: "mid", parallax: 0.35 },
            "world",
            "effects",
            { name: "front", parallax: 1.25 },
            { name: "hud", screen: true },
        ],
    });
    let palette: Palette = PALETTE;
    let sprites: Sprites = paintSprites(palette);
    const backdrop = createBackdrop(renderer.context, palette);
    const particles = createParticles({ max: 260 });
    const sparkle = particles.emitter({ speed: [30, 120], life: [0.3, 0.55], size: [2, 4], colors: ["#f0e442", "#fffbe0"] });
    const dust = particles.emitter({ speed: [10, 50], angle: [Math.PI, Math.PI * 2], life: [0.2, 0.4], size: 3, colors: ["#e8eef2", "#b8c4cc"] });
    const burst = particles.emitter({ speed: [60, 200], life: [0.4, 0.8], size: [2, 5], gravity: 300, colors: ["#d55e00", "#ffffff", "#e69f00"] });
    const trail = createTrail(particles);
    let runner = createAnimator(sprites.clips, "run");
    const text = textStyle({ font: "bold 14px system-ui, sans-serif", fill: PALETTE.text, stroke: PALETTE.textEdge, strokeWidth: 3 });
    const small = textStyle({ font: "bold 11px system-ui, sans-serif", fill: PALETTE.text, stroke: PALETTE.textEdge, strokeWidth: 3 });
    let time = 0;

    renderer.on("sky", (g) => backdrop.sky(g));
    renderer.on("far", (g) => backdrop.far(g));
    renderer.on("mid", (g) => backdrop.mid(g));
    renderer.on("world", (g) => drawTrack(g));
    renderer.on("world", (g) => drawRunner(g));
    renderer.on("effects", (g) => particles.draw(g));
    renderer.on("front", (g) => backdrop.front(g));
    renderer.on("hud", (g) => drawHud(g));

    function drawTrack(g: Painter): void {
        const { track } = source.state();
        const outline = palette.outline;
        for (const island of track.islands) {
            if (!g.visible(island.x, island.y, island.w, WORLD.height)) continue;
            g.rect(island.x, island.y, island.w, WORLD.height - island.y + 40, palette.rock);
            g.rect(island.x + island.w - 8, island.y + 6, 8, WORLD.height - island.y + 40, palette.rockShade);
            // Layers of rock, and tufts of grass at fixed places along the top.
            for (let y = island.y + 22; y < WORLD.height; y += 18) {
                g.rect(island.x + 6, y, island.w - 18, 2, palette.rockShade);
            }
            g.rect(island.x - 2, island.y - 2, island.w + 4, 8, palette.grass);
            g.rect(island.x - 2, island.y - 2, island.w + 4, 2, palette.grassLight);
            for (let x = island.x + 9; x < island.x + island.w - 6; x += 23) {
                g.poly([x, island.y - 2, x + 3, island.y - 7, x + 6, island.y - 2], palette.grass);
            }
            if (outline) g.strokeRect(island.x - 2, island.y - 2, island.w + 4, 8, outline, 1.5);
        }
        for (const cloud of track.clouds) {
            if (!g.visible(cloud.x - 8, cloud.y - 10, cloud.w + 16, 24)) continue;
            for (let i = 0; i <= 3; i += 1) g.circle(cloud.x + (cloud.w * i) / 3, cloud.y + 4, 8, palette.cloud);
            g.rect(cloud.x, cloud.y, cloud.w, 10, palette.cloud);
            if (outline) g.strokeRect(cloud.x, cloud.y, cloud.w, 10, outline, 1.5);
        }
        for (const spike of track.spikes) {
            if (!g.visible(spike.x, spike.y, spike.w, spike.h)) continue;
            const teeth = Math.max(2, Math.round(spike.w / 7));
            const tooth = spike.w / teeth;
            for (let i = 0; i < teeth; i += 1) {
                const x = spike.x + i * tooth;
                g.poly([x, spike.y + spike.h, x + tooth / 2, spike.y, x + tooth, spike.y + spike.h], palette.spike, palette.spikeEdge, 1.5);
            }
        }
        for (const coin of track.coins) {
            if (coin.taken || !g.visible(coin.x - 8, coin.y - 8, 16, 16)) continue;
            const spin = Math.cos(time * 4 + coin.x * 0.05);
            g.sprite(sprites.coin, coin.x, coin.y + Math.sin(time * 3 + coin.x) * 1.5, Math.max(0.2, Math.abs(spin)), 1);
        }
    }

    function drawRunner(g: Painter): void {
        const { runner: r, alive } = source.state();
        trail.draw(g);
        if (!alive && r.y > WORLD.height) return;
        // Blink while the shield of a continue lasts.
        if (r.shield > 0 && Math.floor(r.shield / 8) % 2 === 0) g.alpha = 0.45;
        g.sprite(runner.sprite, r.x - 1, r.y - 2);
        const hat = source.hat();
        const hatSprite = hat ? sprites.hats[hat] : undefined;
        if (hatSprite) g.sprite(hatSprite, r.x + r.w / 2, r.y + 1);
        g.alpha = 1;
    }

    function drawHud(g: Painter): void {
        const state = source.state();
        g.text(`${distance(state)} m`, 12, 10, text);
        g.sprite(sprites.coin, 18, 40);
        g.text(String(state.coins), 28, 33, text);
        g.text(`Best ${source.best()}`, 12, 54, small);
        const label = source.label();
        if (label) g.text(label, WORLD.width - 12 - g.measure(label, text).width, 10, text);
    }

    return {
        camera,
        renderer,
        particles,
        /** Follow a new run from where it starts. */
        follow(state: RunState): void {
            camera.follow(state.runner);
            camera.snap();
            particles.clear();
            trail.clear();
            runner.play("run", true);
        },
        coin: (x: number, y: number): void => sparkle.burst(x, y, 10),
        land: (x: number, y: number): void => dust.burst(x, y, 6),
        crash(x: number, y: number): void {
            burst.burst(x, y, 30);
            camera.shake(6, 0.35);
        },
        wearTrail: (item: string | null): void => trail.wear(item),
        /** The colour-safe setting, and the player's reduced-motion setting for shake and particles. */
        settings(colourSafe: boolean, reducedMotion: boolean): void {
            const next = colourSafe ? SAFE_PALETTE : PALETTE;
            if (next !== palette) {
                palette = next;
                sprites = paintSprites(palette);
                runner = createAnimator(sprites.clips, "run");
                backdrop.setPalette(palette);
            }
            camera.motion = reducedMotion ? REDUCED_MOTION : 1;
            particles.motion = reducedMotion ? REDUCED_MOTION : 1;
        },
        update(dt: number): void {
            time += dt;
            particles.update(dt);
            const { runner: r } = source.state();
            runner.play(r.grounded ? "run" : r.vy < 0 ? "rise" : "fall");
            runner.update(dt);
            if (source.running()) trail.follow(r.x + 2, r.y + r.h * 0.55, dt);
        },
        render(alpha: number, dt: number): void {
            camera.update(dt);
            renderer.render(alpha, dt);
        },
    };
}

export type Art = ReturnType<typeof createArt>;
