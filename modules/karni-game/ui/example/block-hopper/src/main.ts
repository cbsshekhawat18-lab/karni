/**
 * Block Hopper, the example game of @karni/game: move, jump, score, save and
 * a leaderboard. Its rules are a simulation (@karni/game/sim) that moves with
 * @karni/game/collide, its screens are scenes (@karni/game/scenes) with the
 * UI kit (@karni/game/ui), it draws with @karni/game/draw, loads its art by
 * group (@karni/game/assets) and makes its sounds with @karni/game/sfx.
 * Every piece of the package is used here the way a game uses it.
 */
import {
  createAudio,
  createGameClient,
  createInput,
  createPortal,
  createSave,
  createStorage,
  createView,
  createVirtualStick,
  linkPortal,
  pauseOnHidden,
  type BoardEntry,
} from "@karni/game";
import { createAssets, type LoadProgress } from "@karni/game/assets";
import {
  REDUCED_MOTION,
  createCamera,
  createParticles,
  createRenderer,
  textStyle,
  type Painter,
} from "@karni/game/draw";
import { drawCover } from "@karni/game/scenes";
import { createRecorder, createSimLoop, toRunRecord } from "@karni/game/sim";
import {
  applySettings,
  createDevOverlay,
  createSettings,
  createUi,
  guardBoot,
  showBootFailure,
} from "@karni/game/ui";
import { assetHosts } from "virtual:karni-game/assets";
import { createPortalAdapter } from "virtual:karni-game/portal";
import { WORLD, hopperSim, score, type HopperEvent } from "./rules";
import { createGameScenes, type RunResult } from "./scenes";
import { createSounds, playEvent } from "./sound";
import { STAGES, assetManifest, stageInfo, type StageInfo, type StageName } from "./stages";
import { BINDINGS } from "./ui";

interface SaveV2 {
  best: number;
  plays: number;
  muted: boolean;
}

const canvas = document.getElementById("game") as HTMLCanvasElement;
const hud = document.getElementById("hud") as HTMLElement;

const storage = createStorage({ namespace: "block-hopper" });
const save = createSave<SaveV2>({
  storage,
  version: 2,
  defaults: () => ({ best: 0, plays: 0, muted: false }),
  migrations: {
    // Version 1 called the best score "high".
    1: (data) => {
      const old = data as { high?: number; plays?: number };
      return { best: old.high ?? 0, plays: old.plays ?? 0, muted: false };
    },
  },
});
const loaded = save.load();
const progress = loaded.data;

const portal = createPortal(createPortalAdapter());
const client = createGameClient({
  game: "block-hopper",
  storage,
  local: { boards: { high: { title: "High score" } } },
});
const view = createView({ canvas, width: WORLD.width, height: WORLD.height });
const input = createInput({
  target: canvas,
  view,
  bindings: BINDINGS,
});
const stick = createVirtualStick(input, {
  area: () => ({ width: WORLD.width, height: WORLD.height }),
});
const audio = createAudio({ volumes: { effects: 0.6 } });
audio.unlockOn(input);
const sfx = createSounds(audio);
// Pictures, the stage table and every stage's art load from the assets folder, by group.
const assets = createAssets({ manifest: assetManifest, audio, allowHosts: assetHosts });
const ui = createUi({ input });
// Settings have their own save. A mute kept by an older version of the game carries over once.
const settings = createSettings({ storage });
if (progress.muted && settings.loaded.status === "new") settings.set({ muted: true });
applySettings({ store: settings, audio, input, ui });

// The camera keeps the block a third of the way across, and never shows left of the start.
const camera = createCamera({
  view,
  offset: { x: -WORLD.width / 6, y: 0 },
  bounds: { x: 0, y: 0, w: Infinity, h: WORLD.height },
});
const renderer = createRenderer({
  canvas,
  view,
  camera,
  background: "#0d1b2a",
  layers: [
    { name: "sky", screen: true },
    // The stage's backdrop moves at a quarter of the platforms' speed.
    { name: "backdrop", parallax: 0.25 },
    "world",
    "effects",
    { name: "hud", screen: true },
  ],
});
const effects = createParticles({ max: 120 });
const sparkle = effects.emitter({
  speed: [40, 110],
  life: [0.25, 0.5],
  size: [2, 4],
  colors: ["#ffd166", "#fff3c4"],
});
const dust = effects.emitter({
  speed: [10, 40],
  angle: [Math.PI, Math.PI * 2],
  life: [0.2, 0.35],
  size: 3,
  colors: ["#778da9"],
});
// The player's reduced-motion setting scales the shake and the particles down.
const followMotion = (reduced: boolean): void => {
  camera.motion = reduced ? REDUCED_MOTION : 1;
  effects.motion = reduced ? REDUCED_MOTION : 1;
};
followMotion(settings.state.reducedMotion);
settings.subscribe((state) => followMotion(state.reducedMotion));
const text = textStyle({ font: "14px system-ui, sans-serif", fill: "#e0e1dd" });

type Screen = "loading" | "title" | "play" | "over";
let screen: Screen = "title";
const newRun = (seed: number) => {
  const run = createRecorder(hopperSim, { seed });
  // The sim steps its state in place, so the camera follows the same object all run.
  camera.follow(run.sim.state);
  camera.snap();
  return run;
};
let recorder = newRun(1);
let reviveNext = false;
let revived = false;

let stage: StageName | null = null;
let stageData: StageInfo | null = null;
let starting = false;
const memory = (): number =>
  assets.memory("core") + assets.memory("meadow") + assets.memory("cave");

const show = (next: Screen, result?: RunResult): void => {
  screen = next;
  hud.dataset.screen = next;
  hud.dataset.best = String(progress.best);
  // The loading scene is put on by `app.load`, and game over by `app.over`.
  if (result) app.over(result);
  else if (next === "title" || next === "play") app.go(next);
  if (next === "play") portal.gameplayStart();
  else portal.gameplayStop();
};

/** Run a load behind the loading scene. A failure shows the boot failure screen, and Try again loads again. */
const withLoading = (title: string, work: (progress: (p: LoadProgress) => void) => Promise<void>) =>
  new Promise<void>((done) => {
    show("loading");
    const attempt = (): void =>
      app.load({
        title,
        run: (report) => work((p) => report(p.fraction)),
        onDone: done,
        onFailed: (error) => {
          // A readable screen with the files that failed, and Try again loads them again.
          const failure = showBootFailure({
            error,
            onRetry: () => {
              failure.destroy();
              attempt();
            },
          });
        },
      });
    attempt();
  });

/** The next run's stage alternates. Its art loads first, and the last stage's art is freed after. */
const start = async (): Promise<void> => {
  if (starting) return;
  starting = true;
  try {
    const next = STAGES[progress.plays % STAGES.length] as StageName;
    if (!assets.isLoaded(next)) {
      await withLoading(`Loading ${next}`, async (onProgress) => {
        await assets.load(next, { onProgress });
      });
    }
    const last = stage;
    stage = next;
    stageData = stageInfo(assets, next);
    if (last && last !== next) assets.unload(last);
    hud.dataset.stage = next;
    hud.dataset.artMemory = String(memory());
    hud.dataset.groups = (["core", ...STAGES] as const).filter((g) => assets.isLoaded(g)).join(",");
    sfx.music(stageData.theme === "cave" ? "theme-cave" : "theme-meadow", {
      fade: 1.2,
      volume: 0.7,
    });
    // The page may use any clock or Math.random: only src/rules may not.
    recorder = newRun(Math.floor(Math.random() * 2 ** 31));
    effects.clear();
    revived = false;
    show("play");
  } finally {
    starting = false;
  }
};

/** Send the score with its run, then read the top of the board. Offline, the device's board. */
const sendScore = async (value: number): Promise<readonly BoardEntry[]> => {
  const run = toRunRecord(recorder.finish());
  try {
    await client.submitScore("high", value, { run });
    return (await client.leaderboard("high", { limit: 5 })).entries;
  } catch {
    return [];
  }
};

const finish = (): void => {
  const value = recorder.sim.score;
  progress.plays += 1;
  if (value > progress.best) {
    progress.best = value;
    portal.happyMoment();
  }
  save.write(progress);
  const board = sendScore(value);
  show("over", {
    score: value,
    best: progress.best,
    canContinue: !revived && portal.canShowRewarded(),
    board,
  });
  client.track("run_over", { score: value });
  void portal.interstitial("game-over");
};

/** A rewarded ad brings the block back once a run; the revive reaches the rules as an input. */
const continueRun = (): void => {
  if (revived || screen !== "over") return;
  if (!portal.canShowRewarded()) {
    // An interstitial may still be playing: say so rather than do nothing.
    ui.toast("No ad to watch right now. Try again in a moment.");
    return;
  }
  void portal.rewarded("continue").then((rewarded) => {
    if (!rewarded) return;
    revived = true;
    reviveNext = true;
    show("play");
  });
};

/** Menus, keys and effects: runs on every fixed step, whatever the screen. */
const beforeStep = (dt: number): void => {
  effects.update(dt);
  if (input.pressed("mute")) {
    settings.set({ muted: !settings.state.muted });
  }
  if (screen === "play") return;
  if (input.pressed("jump")) void start();
  if (screen === "over" && input.pressed("revive")) continueRun();
};

/** The player's input for one tick of the rules, read once per step. */
const readInput = () => {
  const step = {
    left: input.held("left"),
    right: input.held("right"),
    jump: input.pressed("jump"),
    revive: reviveNext,
  };
  reviveNext = false;
  // The jump edge is read by the first step of the frame only.
  input.endFrame();
  return step;
};

const onEvents = (events: readonly HopperEvent[]): void => {
  const hopper = recorder.sim.state;
  for (const event of events) {
    playEvent(sfx, event);
    if (event === "coin") sparkle.burst(hopper.x + hopper.w / 2, hopper.y, 12);
    if (event === "land") dust.burst(hopper.x + hopper.w / 2, hopper.y + hopper.h, 6);
    if (event === "fall") finish();
  }
};

renderer.on("sky", (g) => g.rect(0, 0, WORLD.width, WORLD.height, "#1b263b"));
renderer.on("backdrop", (g) => {
  // A group's images are closed when it unloads: draw only from a loaded group.
  if (!stage || !assets.isLoaded(stage)) return;
  const backdrop = assets.image(stage, "bg");
  // The art repeats at its own width across what this layer shows.
  const first = Math.floor(g.left / backdrop.width) * backdrop.width;
  for (let x = first; x < g.left + g.width; x += backdrop.width) {
    g.ctx.drawImage(backdrop.source, x, 0);
  }
});
renderer.on("world", (g) => {
  const hopper = recorder.sim.state;
  const art = assets.isLoaded("core");
  // Off-screen platforms and coins are culled by the painter.
  for (const p of hopper.platforms) g.rect(p.x, p.y, p.w, p.h, stageData?.platform ?? "#778da9");
  for (const c of hopper.pickups) {
    if (c.taken || !g.visible(c.x - 5, c.y - 5, 10, 10)) continue;
    if (art) g.ctx.drawImage(assets.image("core", "coin").source, c.x - 5, c.y - 5);
    else g.rect(c.x - 5, c.y - 5, 10, 10, "#ffd166");
  }
  if (art) g.ctx.drawImage(assets.image("core", "hopper").source, hopper.x, hopper.y);
  else g.rect(hopper.x, hopper.y, hopper.w, hopper.h, "#ef476f");
});
renderer.on("effects", (g) => effects.draw(g));
renderer.on("hud", (g: Painter) => {
  const hopper = recorder.sim.state;
  g.text(`Score ${score(hopper)}   Best ${progress.best}`, 10, 8, text);
  if (portal.adPlaying) g.text("Ad playing...", 200, 240, text);
  stick.draw(g.ctx);
});

/** The frame time of the frame being drawn, for the camera and the renderer. */
let frameDt = 0;
/** The world under the title and the play scene: the scenes call it from their draw. */
const render = (alpha: number): void => {
  hud.dataset.score = String(score(recorder.sim.state));
  camera.update(frameDt);
  renderer.render(alpha, frameDt);
  drawCover(renderer.context, app.cover, canvas.width, canvas.height, "#0d1b2a");
};

// The scene stack runs on every fixed step (menus, keys, the pause overlay) and
// the rules run one tick after it while a run is on screen.
const loop = createSimLoop({
  target: () => recorder,
  input: readInput,
  beforeStep: (dt) => app.update(dt),
  active: () => screen === "play" && app.stack.top?.name === "play",
  onEvents,
  render: (alpha, dt) => {
    frameDt = dt;
    app.draw(alpha);
  },
  afterFrame: () => input.endFrame(),
});
const toTitle = (): void => {
  recorder = newRun(1);
  show("title");
};
const app = createGameScenes(
  { loop, input, audio, save, portal, client, ui, settings },
  { update: beforeStep, render, start: () => void start(), continueRun, toTitle },
);
createDevOverlay(ui, {
  loop,
  entities: () =>
    recorder.sim.state.platforms.length + recorder.sim.state.pickups.length + effects.count,
});
pauseOnHidden([loop, audio]);
// A pause menu pauses the loop, and the sound stops with it.
audio.follow(loop);
linkPortal(portal, { audio, loop, input });

void guardBoot(async () => {
  portal.loadingStart();
  loop.start();
  await Promise.all([portal.init(), client.boot()]);
  await client.signInGuest();
  // The shared art, the fonts and the stage table load behind the loading scene.
  await withLoading("Loading", async (onProgress) => {
    await assets.load("core", { onProgress });
    await assets.fontsReady();
  });
  portal.loadingFinished();
  hud.dataset.loaded = loaded.status;
  show("title");
});

if (__KARNI_GAME_DEV__) {
  // A development handle, dropped from every build by the preset's flag.
  (window as unknown as Record<string, unknown>).__blockHopper = {
    loop,
    client,
    portal,
    assets,
    sfx,
    audio,
  };
}
