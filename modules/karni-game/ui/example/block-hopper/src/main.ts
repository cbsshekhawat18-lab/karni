/**
 * Block Hopper, the example game of @karni/game: move, jump, score, save and
 * a leaderboard, drawn with @karni/game/draw and moved with
 * @karni/game/collide. Every piece of the package is used here the way a
 * game uses it.
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
} from "@karni/game/ui";
import { createPortalAdapter } from "virtual:karni-game/portal";
import { WORLD, hopperSim, score, type HopperEvent } from "./rules";
import { createGameScenes } from "./scenes";
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
  layers: [{ name: "sky", screen: true }, "world", "effects", { name: "hud", screen: true }],
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
const message = textStyle({ font: "14px system-ui, sans-serif", fill: "#e0e1dd", wrap: 400 });

type Screen = "title" | "play" | "over";
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
let board: BoardEntry[] = [];
let revived = false;

const blip = (frequency: number): void => {
  const ctx = audio.context;
  if (!ctx || !audio.unlocked) return;
  const length = Math.floor(ctx.sampleRate * 0.08);
  const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < length; i += 1)
    data[i] = Math.sin((i / ctx.sampleRate) * frequency * Math.PI * 2) * (1 - i / length) * 0.4;
  audio.play(buffer);
};

const show = (next: Screen): void => {
  screen = next;
  hud.dataset.screen = next;
  hud.dataset.best = String(progress.best);
  app.go(next);
  if (next === "play") portal.gameplayStart();
  else portal.gameplayStop();
};

const start = (): void => {
  // The page may use any clock or Math.random: only src/rules may not.
  recorder = newRun(Math.floor(Math.random() * 2 ** 31));
  effects.clear();
  revived = false;
  show("play");
};

const finish = async (): Promise<void> => {
  const value = recorder.sim.score;
  progress.plays += 1;
  if (value > progress.best) {
    progress.best = value;
    portal.happyMoment();
  }
  save.write(progress);
  show("over");
  const run = toRunRecord(recorder.finish());
  try {
    await client.submitScore("high", value, { run });
    board = (await client.leaderboard("high", { limit: 5 })).entries;
  } catch {
    board = [];
  }
  client.track("run_over", { score: value });
  void portal.interstitial("game-over");
};

/** Menus, keys and effects: runs on every fixed step, whatever the screen. */
const beforeStep = (dt: number): void => {
  effects.update(dt);
  if (input.pressed("mute")) {
    settings.set({ muted: !settings.state.muted });
  }
  if (screen === "play") return;
  if (input.pressed("jump")) start();
  if (screen === "over" && !revived && input.pressed("revive")) {
    void portal.rewarded("continue").then((rewarded) => {
      if (!rewarded) return;
      revived = true;
      reviveNext = true;
      show("play");
    });
  }
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
    if (event === "jump") blip(520);
    if (event === "coin") {
      blip(880);
      sparkle.burst(hopper.x + hopper.w / 2, hopper.y, 12);
    }
    if (event === "land") dust.burst(hopper.x + hopper.w / 2, hopper.y + hopper.h, 6);
    if (event === "fall") void finish();
  }
};

renderer.on("sky", (g) => g.rect(0, 0, WORLD.width, WORLD.height, "#1b263b"));
renderer.on("world", (g) => {
  const hopper = recorder.sim.state;
  // Off-screen platforms and coins are culled by the painter.
  for (const p of hopper.platforms) g.rect(p.x, p.y, p.w, p.h, "#778da9");
  for (const c of hopper.pickups) if (!c.taken) g.rect(c.x - 5, c.y - 5, 10, 10, "#ffd166");
  g.rect(hopper.x, hopper.y, hopper.w, hopper.h, "#ef476f");
});
renderer.on("effects", (g) => effects.draw(g));
renderer.on("hud", (g: Painter) => {
  const hopper = recorder.sim.state;
  g.text(`Score ${score(hopper)}   Best ${progress.best}`, 10, 8, text);
  if (screen === "over") {
    g.text("Fell! Space or tap to hop again. R: watch an ad to continue", 40, 100, message);
    board.forEach((entry, index) =>
      g.text(`${entry.rank}. ${entry.handle} ${entry.value}`, 180, 130 + index * 18, text),
    );
  }
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
  { update: beforeStep, render, start, toTitle },
);
createDevOverlay(ui, {
  loop,
  entities: () =>
    recorder.sim.state.platforms.length + recorder.sim.state.pickups.length + effects.count,
});
pauseOnHidden([loop, audio]);
linkPortal(portal, { audio, loop, input });

void guardBoot(async () => {
  portal.loadingStart();
  await Promise.all([portal.init(), client.boot()]);
  await client.signInGuest();
  portal.loadingFinished();
  hud.dataset.loaded = loaded.status;
  show("title");
  loop.start();
});

if (__KARNI_GAME_DEV__) {
  // A development handle, dropped from every build by the preset's flag.
  (window as unknown as Record<string, unknown>).__blockHopper = { loop, client, portal };
}
