/**
 * Block Hopper, the example game of @karni/game: move, jump, score, save and
 * a leaderboard, on plain canvas. Every piece of the package is used here
 * the way a game uses it.
 */
import {
  POINTER,
  STICK,
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
import { createRecorder, createSimLoop, toRunRecord } from "@karni/game/sim";
import { createPortalAdapter } from "virtual:karni-game/portal";
import { WORLD, hopperSim, score, type HopperEvent } from "./rules";

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

type Screen = "title" | "play" | "over";
let screen: Screen = "title";
const newRun = (seed: number) => createRecorder(hopperSim, { seed });
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
  if (next === "play") portal.gameplayStart();
  else portal.gameplayStop();
};

const start = (): void => {
  // The page may use any clock or Math.random: only src/rules may not.
  recorder = newRun(Math.floor(Math.random() * 2 ** 31));
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

/** Menus and keys: runs on every step, whatever the screen. */
const beforeStep = (): void => {
  if (input.pressed("mute")) {
    progress.muted = !progress.muted;
    audio.setMuted("player", progress.muted);
    save.write(progress);
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
  for (const event of events) {
    if (event === "jump") blip(520);
    if (event === "coin") blip(880);
    if (event === "fall") void finish();
  }
};

const render = (): void => {
  const hopper = recorder.sim.state;
  hud.dataset.score = String(score(hopper));
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
  if (screen === "title")
    context.fillText("Block Hopper: arrows or stick to move, space or tap to jump", 40, 130);
  if (screen === "over") {
    context.fillText("Fell! Space or tap to hop again. R: watch an ad to continue", 40, 110);
    board.forEach((entry, index) =>
      context.fillText(`${entry.rank}. ${entry.handle} ${entry.value}`, 180, 140 + index * 18),
    );
  }
  if (portal.adPlaying) context.fillText("Ad playing...", 200, 250);
  stick.draw(context);
};

const loop = createSimLoop({
  target: () => recorder,
  input: readInput,
  beforeStep,
  active: () => screen === "play",
  onEvents,
  render,
  afterFrame: () => input.endFrame(),
});
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
