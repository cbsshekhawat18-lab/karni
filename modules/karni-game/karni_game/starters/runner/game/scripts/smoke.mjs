// The game played in headless Chromium (npm run smoke), on @karni/game/smoke: built for a
// portal with no server (itch.io: the game plays on the device), served for the run, played
// by touch on a phone and by keys on a desktop, then booted again with every stored value
// broken. It fails on a console error, a page error, a failed request, a canvas that never
// changed, or frames slower than the budget (KARNI_SMOKE_FRAME_MULTIPLIER loosens it on a
// slow machine). `npx playwright install chromium` once before the first run.
import { fileURLToPath } from "node:url";
import { runSmoke } from "@karni/game/smoke";
import { build } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const dir = fileURLToPath(new URL("../dist-smoke/", import.meta.url));
process.env.KARNI_GAME_PORTAL = "itch";
await build({ root, logLevel: "warn", build: { outDir: dir, emptyOutDir: true } });

/** The run is on (or over) and went some way. */
async function check(page, phase) {
    const hud = await page.evaluate(() => ({ ...document.getElementById("hud")?.dataset }));
    if (hud.screen !== "play" && hud.screen !== "over") {
        throw new Error(`${phase}: the run never started (the screen is ${hud.screen})`);
    }
}
const ready = async (page) => {
    await page.waitForFunction(() => document.getElementById("hud")?.dataset.screen === "title", null, {
        timeout: 20_000,
    });
};
const taps = (start, count, every, step) => Array.from({ length: count }, (_, i) => step(start + i * every));

const runs = [
    {
        name: "phone, by touch",
        viewport: { width: 390, height: 844 },
        touch: true,
        // Taps near the top: clear of the title's panel, still on the canvas.
        script: taps(0.5, 14, 0.45, (at) => ({ at, tap: { x: 0.5, y: 0.12 } })),
    },
    {
        name: "desktop, by keys",
        viewport: { width: 1280, height: 720 },
        touch: false,
        script: taps(0.5, 14, 0.45, (at) => ({ at, key: "Space" })),
    },
];
let failed = false;
for (const run of runs) {
    let result;
    try {
        result = await runSmoke({ dir, seconds: 8, ready, check, frameBudget: { p95: 40 }, ...run });
    } catch (error) {
        console.log(`FAIL ${run.name}: ${error instanceof Error ? error.message : String(error)}`);
        failed = true;
        continue;
    }
    const stats = result.frameStats;
    const frames = stats ? ` p95 ${stats.p95.toFixed(1)} ms, slowest ${stats.max.toFixed(1)} ms` : "";
    console.log(`${result.ok ? "ok  " : "FAIL"} ${run.name}:${frames}`);
    for (const problem of result.problems) console.log(`     ${problem}`);
    failed ||= !result.ok;
}
process.exit(failed ? 1 : 0);
