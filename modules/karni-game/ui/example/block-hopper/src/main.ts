/**
 * Block Hopper, the example game of @karni/game: move, jump, score, save and
 * a leaderboard, on plain canvas. Every piece of the package is used here
 * the way a game uses it.
 */
import {
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
import { drawCover } from "@karni/game/scenes";
import {
  applySettings,
  createDevOverlay,
  createSettings,
  createUi,
  guardBoot,
} from "@karni/game/ui";
import { createPortalAdapter } from "virtual:karni-game/portal";
import { createGameScenes } from "./scenes";
import { BINDINGS } from "./ui";
import { WORLD, createHopper, revive, score, stepHopper, type Hopper } from "./core";

interface SaveV2 {
  best: number;
  plays: number;
  muted: boolean;
}

const canvas = document.getElementById("game") as HTMLCanvasElement;
const hud = document.getElementById("hud") as HTMLElement;
const context = canvas.getContext("2d") as CanvasRenderingContext2D;

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

type Screen = "title" | "play" | "over";
let screen: Screen = "title";
let hopper: Hopper = createHopper(1);
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
  app.go(next);
  if (next === "play") portal.gameplayStart();
  else portal.gameplayStop();
};

const start = (): void => {
  hopper = createHopper(Math.floor(Math.random() * 2 ** 31));
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
  if (input.pressed("mute")) {
    settings.set({ muted: !settings.state.muted });
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
    if (event === "coin") blip(880);
    if (event === "fall") void finish();
  }
  hud.dataset.score = String(score(hopper));
  // The jump edge is read by the first step of the frame only.
  input.endFrame();
};

const render = (): void => {
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.fillStyle = "#0d1b2a";
  context.fillRect(0, 0, canvas.width, canvas.height);
  view.apply(context);
  context.fillStyle = "#1b263b";
  context.fillRect(0, 0, WORLD.width, WORLD.height);
  const cameraX = Math.max(0, hopper.x - WORLD.width / 3);
  context.save();
  context.translate(-cameraX, 0);
  context.fillStyle = "#778da9";
  for (const p of hopper.platforms)
    if (p.x + p.w > cameraX && p.x < cameraX + WORLD.width) context.fillRect(p.x, p.y, p.w, 8);
  context.fillStyle = "#ffd166";
  for (const c of hopper.pickups) if (!c.taken) context.fillRect(c.x - 5, c.y - 5, 10, 10);
  context.fillStyle = "#ef476f";
  context.fillRect(hopper.x, hopper.y, WORLD.size, WORLD.size);
  context.restore();
  context.fillStyle = "#e0e1dd";
  context.font = "14px system-ui, sans-serif";
  context.fillText(`Score ${score(hopper)}   Best ${progress.best}`, 10, 20);
  if (screen === "over") {
    context.fillText("Fell! Space or tap to hop again. R: watch an ad to continue", 40, 110);
    board.forEach((entry, index) =>
      context.fillText(`${entry.rank}. ${entry.handle} ${entry.value}`, 180, 140 + index * 18),
    );
  }
  if (portal.adPlaying) context.fillText("Ad playing...", 200, 250);
  stick.draw(context);
  drawCover(context, app.cover, canvas.width, canvas.height, "#0d1b2a");
};

const loop = createLoop({
  step: WORLD.step,
  update: (dt) => app.update(dt),
  render: (alpha) => app.draw(alpha),
  afterFrame: () => input.endFrame(),
});
const toTitle = (): void => {
  hopper = createHopper(1);
  show("title");
};
const app = createGameScenes(
  { loop, input, audio, save, portal, client, ui, settings },
  { update, render, start, toTitle },
);
createDevOverlay(ui, { loop, entities: () => hopper.platforms.length + hopper.pickups.length });
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
