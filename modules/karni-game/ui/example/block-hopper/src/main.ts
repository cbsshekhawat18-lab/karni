/**
 * Block Hopper, the example game of @karni/game: move, jump, score, save and
 * a leaderboard, drawn with @karni/game/draw and moved with
 * @karni/game/collide. Every piece of the package is used here the way a
 * game uses it.
 */
import {
  POINTER,
  STICK,
  createAudio,
  createGameClient,
  createInput,
  createLoop,
  createPortal,
  createSave,
  createStorage,
  createView,
  createVirtualStick,
  linkPortal,
  pauseOnHidden,
  type BoardEntry,
  type RunRecord,
} from "@karni/game";
import {
  createCamera,
  createParticles,
  createRenderer,
  textStyle,
  type Painter,
} from "@karni/game/draw";
import { createPortalAdapter } from "virtual:karni-game/portal";
import { WORLD, createHopper, revive, score, stepHopper, type Hopper } from "./core";

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
  bindings: {
    left: ["ArrowLeft", "KeyA", STICK.left],
    right: ["ArrowRight", "KeyD", STICK.right],
    jump: ["Space", "ArrowUp", "KeyW", POINTER],
    mute: ["KeyM"],
    revive: ["KeyR"],
  },
});
const stick = createVirtualStick(input, {
  area: () => ({ width: WORLD.width, height: WORLD.height }),
});
const audio = createAudio({ volumes: { effects: 0.6 } });
audio.unlockOn(input);
audio.setMuted("player", progress.muted);

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
const text = textStyle({ font: "14px system-ui, sans-serif", fill: "#e0e1dd" });
const message = textStyle({ font: "14px system-ui, sans-serif", fill: "#e0e1dd", wrap: 400 });

type Screen = "title" | "play" | "over";
let screen: Screen = "title";
let hopper: Hopper = createHopper(1);
camera.follow(hopper);
camera.snap();
let inputs: [number, string][] = [];
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
  if (next === "play") portal.gameplayStart();
  else portal.gameplayStop();
};

const start = (): void => {
  hopper = createHopper(Math.floor(Math.random() * 2 ** 31));
  camera.follow(hopper);
  camera.snap();
  effects.clear();
  inputs = [];
  revived = false;
  show("play");
};

const finish = async (): Promise<void> => {
  const value = score(hopper);
  progress.plays += 1;
  if (value > progress.best) {
    progress.best = value;
    portal.happyMoment();
  }
  save.write(progress);
  show("over");
  const run: RunRecord = {
    seed: String(hopper.seed),
    inputs,
    duration_ms: Math.round(hopper.time * 1000),
  };
  try {
    await client.submitScore("high", value, { run });
    board = (await client.leaderboard("high", { limit: 5 })).entries;
  } catch {
    board = [];
  }
  client.track("run_over", { score: value });
  void portal.interstitial("game-over");
};

const update = (dt: number): void => {
  effects.update(dt);
  if (input.pressed("mute")) {
    progress.muted = !progress.muted;
    audio.setMuted("player", progress.muted);
    save.write(progress);
  }
  if (screen !== "play") {
    if (input.pressed("jump")) start();
    if (screen === "over" && !revived && input.pressed("revive")) {
      void portal.rewarded("continue").then((rewarded) => {
        if (!rewarded) return;
        revived = true;
        revive(hopper);
        show("play");
      });
    }
    return;
  }
  const step = {
    left: input.held("left"),
    right: input.held("right"),
    jump: input.pressed("jump"),
  };
  if (step.jump) inputs.push([Math.round(hopper.time * 1000), "jump"]);
  for (const event of stepHopper(hopper, step, dt)) {
    if (event === "jump") blip(520);
    if (event === "coin") {
      blip(880);
      sparkle.burst(hopper.x + hopper.w / 2, hopper.y, 12);
    }
    if (event === "land") dust.burst(hopper.x + hopper.w / 2, hopper.y + hopper.h, 6);
    if (event === "fall") void finish();
  }
  hud.dataset.score = String(score(hopper));
  // The jump edge is read by the first step of the frame only.
  input.endFrame();
};

renderer.on("sky", (g) => g.rect(0, 0, WORLD.width, WORLD.height, "#1b263b"));
renderer.on("world", (g) => {
  // Off-screen platforms and coins are culled by the painter.
  for (const p of hopper.platforms) g.rect(p.x, p.y, p.w, p.h, "#778da9");
  for (const c of hopper.pickups) if (!c.taken) g.rect(c.x - 5, c.y - 5, 10, 10, "#ffd166");
  g.rect(hopper.x, hopper.y, hopper.w, hopper.h, "#ef476f");
});
renderer.on("effects", (g) => effects.draw(g));
renderer.on("hud", (g: Painter) => {
  g.text(`Score ${score(hopper)}   Best ${progress.best}`, 10, 8, text);
  if (screen === "title") {
    g.text("Block Hopper: arrows or stick to move, space or tap to jump", 40, 120, message);
  }
  if (screen === "over") {
    g.text("Fell! Space or tap to hop again. R: watch an ad to continue", 40, 100, message);
    board.forEach((entry, index) =>
      g.text(`${entry.rank}. ${entry.handle} ${entry.value}`, 180, 130 + index * 18, text),
    );
  }
  if (portal.adPlaying) g.text("Ad playing...", 200, 240, text);
  stick.draw(g.ctx);
});

const render = (alpha: number, dt: number): void => {
  camera.update(dt);
  renderer.render(alpha, dt);
};

const loop = createLoop({ step: WORLD.step, update, render, afterFrame: () => input.endFrame() });
pauseOnHidden([loop, audio]);
linkPortal(portal, { audio, loop, input });

void (async () => {
  portal.loadingStart();
  await Promise.all([portal.init(), client.boot()]);
  await client.signInGuest();
  portal.loadingFinished();
  hud.dataset.loaded = loaded.status;
  show("title");
  loop.start();
})();

if (__KARNI_GAME_DEV__) {
  // A development handle, dropped from every build by the preset's flag.
  (window as unknown as Record<string, unknown>).__blockHopper = { loop, client, portal };
}
