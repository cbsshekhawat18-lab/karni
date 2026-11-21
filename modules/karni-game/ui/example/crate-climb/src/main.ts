/**
 * Crate Climb, the second example scene of @karni/game: a level three
 * screens wide and two high. It shows the camera following with a dead zone
 * and zooming, parallax layers, sprites cut from sheets and animated,
 * particles, tweens on the game clock and on real time, the box mover with
 * one-way ledges, trigger zones, hit-stop and slow motion.
 */
import {
  POINTER,
  STICK,
  createInput,
  createLoop,
  createView,
  createVirtualStick,
  pauseOnHidden,
} from "@karni/game";
import {
  createAnimator,
  createCamera,
  createParticles,
  createPool,
  createRenderer,
  createTweens,
  inOutSine,
  outBack,
  outQuad,
  textStyle,
  type Painter,
} from "@karni/game/draw";
import { paintArt } from "./art";
import { LEVEL, createClimb, stepClimb, type ClimbEvent } from "./level";

const WIDTH = 480;
const HEIGHT = 270;
const canvas = document.getElementById("game") as HTMLCanvasElement;
const hud = document.getElementById("hud") as HTMLElement;
const view = createView({ canvas, width: WIDTH, height: HEIGHT });
const input = createInput({
  target: canvas,
  view,
  bindings: {
    left: ["ArrowLeft", "KeyA", STICK.left],
    right: ["ArrowRight", "KeyD", STICK.right],
    jump: ["Space", "ArrowUp", "KeyW", POINTER],
    down: ["ArrowDown", "KeyS", STICK.down],
  },
});
const stick = createVirtualStick(input, { area: () => ({ width: WIDTH, height: HEIGHT }) });
const art = paintArt();

type Screen = "title" | "play" | "goal";
let screen: Screen = "title";
let climb = createClimb();

const camera = createCamera({
  view,
  bounds: { x: 0, y: 0, w: LEVEL.width, h: LEVEL.height },
  deadZone: { w: 60, h: 50 },
  // The climber sits a little below the centre: more of the way up shows.
  offset: { x: 0, y: 20 },
  smoothing: 7,
});
camera.follow(climb.player);
camera.snap();

const renderer = createRenderer({
  canvas,
  view,
  camera,
  background: "#0b132b",
  smoothing: false,
  layers: [
    { name: "sky", screen: true },
    { name: "hills", parallax: 0.35 },
    "world",
    "effects",
    { name: "hud", screen: true },
  ],
});

/** Tweens of things in the world run on the game clock: they slow with it and stop on a hit. */
const worldTweens = createTweens();
/** The HUD's and the camera's run on real time, in render. */
const screenTweens = createTweens();

const particles = createParticles({ max: 400 });
const sparkle = particles.emitter({
  speed: [40, 150],
  life: [0.3, 0.7],
  size: [2, 4],
  drag: 2,
  colors: ["#ffd166", "#fff3c4", "#f72585"],
  blend: "lighter",
});
const dust = particles.emitter({
  speed: [20, 80],
  angle: [Math.PI * 1.05, Math.PI * 1.95],
  life: [0.25, 0.5],
  size: [2, 5],
  endSize: 0.3,
  gravity: 220,
  colors: ["#8d99ae", "#adb5bd"],
});
const trail = particles.emitter({
  speed: [5, 20],
  angle: [-Math.PI * 0.65, -Math.PI * 0.35],
  life: [0.2, 0.4],
  size: 2,
  colors: ["#4cc9f0"],
});

const hero = createAnimator(art.hero, "idle");
const gemSpin = createAnimator(art.gem, "spin");

/** Taken gems float up and fade: a few pooled ghosts, each moved by a tween. */
interface Ghost {
  x: number;
  y: number;
  alpha: number;
  scale: number;
}
const ghosts = createPool<Ghost>({
  create: () => ({ x: 0, y: 0, alpha: 1, scale: 1 }),
  max: 16,
  prefill: 16,
});
const counter = { scale: 1 };
const title = { y: -60, alpha: 1 };
const banner = { y: -60 };
screenTweens.to(title, { y: 92 }, 0.9, { ease: outBack });

const hudText = textStyle({
  font: "bold 14px system-ui, sans-serif",
  fill: "#fff3c4",
  stroke: "#0b132b",
  strokeWidth: 3,
});
const big = textStyle({
  font: "bold 30px system-ui, sans-serif",
  fill: "#fff3c4",
  stroke: "#0b132b",
  strokeWidth: 5,
  align: "center",
});
const small = textStyle({
  font: "13px system-ui, sans-serif",
  fill: "#e0e1dd",
  align: "center",
  wrap: 360,
});

const sky = renderer.context.createLinearGradient(0, 0, 0, HEIGHT);
sky.addColorStop(0, "#0b132b");
sky.addColorStop(1, "#3a506b");

/** Far hills as flat point lists, laid once across the width the parallax layer shows. */
const hills: number[][] = [];
for (let x = -40; x < LEVEL.width * 0.35 + WIDTH + 80; x += 90) {
  const top = 150 + ((x * 37) % 50);
  // The hills reach well below the screen: the layer moves up and down with the camera.
  hills.push([x, HEIGHT * 3, x, top + 60, x + 60, top, x + 130, top + 70, x + 130, HEIGHT * 3]);
}

let elapsed = 0;
let goalTime = 0;
let reported = "";

const report = (): void => {
  const p = climb.player;
  const next = `${screen}|${climb.taken}|${Math.round(camera.x)}|${Math.round(p.x)}|${camera.zoom.toFixed(2)}`;
  if (next === reported) return;
  reported = next;
  hud.dataset.screen = screen;
  hud.dataset.gems = String(climb.taken);
  hud.dataset.cameraX = String(Math.round(camera.x));
  hud.dataset.playerX = String(Math.round(p.x));
  hud.dataset.zoom = camera.zoom.toFixed(2);
};

const begin = (): void => {
  screen = "play";
  screenTweens.to(title, { alpha: 0 }, 0.3);
};

const restart = (): void => {
  climb = createClimb();
  camera.follow(climb.player);
  camera.zoom = 1;
  camera.snap();
  particles.clear();
  ghosts.clear();
  worldTweens.clear();
  banner.y = -60;
  screen = "play";
};

const react = (event: ClimbEvent): void => {
  switch (event.type) {
    case "jump":
      dust.burst(event.x, event.y, 4);
      break;
    case "land":
      dust.burst(event.x, event.y, event.hard ? 18 : 5);
      if (event.hard) {
        camera.shake(4, 0.25);
        loop.hitStop(70);
      }
      break;
    case "gem": {
      sparkle.burst(event.x, event.y, 18);
      const ghost = ghosts.acquire();
      if (ghost) {
        Object.assign(ghost, { x: event.x, y: event.y, alpha: 1, scale: 1 });
        worldTweens.to(ghost, { y: event.y - 26, alpha: 0, scale: 2 }, 0.6, {
          ease: outQuad,
          onDone: () => ghosts.release(ghost),
        });
      }
      screenTweens.cancelOf(counter);
      screenTweens.to(counter, { scale: 1.7 }, 0.08, {
        onDone: () => screenTweens.to(counter, { scale: 1 }, 0.3, { ease: outBack }),
      });
      break;
    }
    case "checkpoint":
      sparkle.burst(event.x, event.y, 10);
      break;
    case "respawn":
      camera.shake(6, 0.3);
      loop.hitStop(120);
      dust.burst(event.x, event.y, 12);
      break;
    case "goal":
      screen = "goal";
      goalTime = 0;
      sparkle.burst(event.x + 8, event.y + 10, 40);
      // A moment of slow motion, and the camera closes in.
      loop.timeScale = 0.35;
      screenTweens.to(loop, { timeScale: 1 }, 1.2, { delay: 0.6 });
      screenTweens.to(camera, { zoom: 1.6 }, 1.2, { ease: inOutSine });
      screenTweens.to(banner, { y: 70 }, 0.8, { ease: outBack, delay: 0.3 });
      break;
  }
};

const update = (dt: number): void => {
  elapsed += dt;
  worldTweens.update(dt);
  particles.update(dt);
  gemSpin.update(dt);
  if (screen === "title") {
    if (input.pressed("jump")) begin();
    input.endFrame();
    return;
  }
  if (screen === "goal") {
    goalTime += dt;
    if (goalTime > 1 && input.pressed("jump")) restart();
  }
  const p = climb.player;
  const events = stepClimb(climb, {
    left: input.held("left"),
    right: input.held("right"),
    jump: input.pressed("jump"),
    down: input.held("down"),
  });
  for (const event of events) react(event);
  hero.play(!p.grounded ? "jump" : p.running ? "run" : "idle");
  hero.update(dt);
  if (p.running) trail.flow(p.x + (p.facing > 0 ? 0 : p.w), p.y + p.h - 3, 30, dt);
  // The jump edge is read by the first step of the frame only.
  input.endFrame();
};

let current: Painter | null = null;
const drawGhost = (ghost: Ghost): void => {
  if (!current) return;
  current.alpha = ghost.alpha;
  current.sprite(gemSpin.sprite, ghost.x, ghost.y, ghost.scale, ghost.scale);
};

renderer.on("sky", (g) => g.rect(0, 0, WIDTH, HEIGHT, sky));
renderer.on("hills", (g) => {
  for (const hill of hills) g.poly(hill, "#1c2541");
});
renderer.on("world", (g) => {
  for (const s of climb.solids) {
    if (s.w === 32 && s.h === 32) {
      g.sprite(art.crate, s.x, s.y);
    } else if (s.oneWay) {
      g.rect(s.x, s.y, s.w, s.h, "#6c757d");
      g.rect(s.x, s.y, s.w, 2, "#ced4da");
    } else {
      g.rect(s.x, s.y, s.w, s.h, "#2d3e50");
      g.rect(s.x, s.y, s.w, 3, "#5bc0be");
    }
  }
  for (const gem of climb.gems) {
    if (!gem.taken) g.sprite(gemSpin.sprite, gem.x, gem.y + Math.sin(elapsed * 3 + gem.x) * 2);
  }
  g.sprite(art.flag, climb.goal.x, climb.goal.y + climb.goal.h);
  const p = climb.player;
  g.sprite(hero.sprite, p.x + p.w / 2, p.y + p.h, p.facing, 1);
  current = g;
  ghosts.forEach(drawGhost);
  current = null;
});
renderer.on("effects", (g) => particles.draw(g));
renderer.on("hud", (g) => {
  g.sprite(gemSpin.sprite, 18, 18, counter.scale, counter.scale);
  g.text(`${climb.taken} / ${climb.gems.length}`, 32, 11, hudText);
  if (title.alpha > 0) {
    g.alpha = title.alpha;
    g.text("Crate Climb", WIDTH / 2, title.y, big);
    g.text(
      "Arrows or the stick to move. Space or a tap to jump. Down drops.",
      WIDTH / 2,
      title.y + 42,
      small,
    );
    g.alpha = 1;
  }
  if (screen === "goal") {
    g.text("At the top!", WIDTH / 2, banner.y, big);
    g.text(
      `${climb.taken} of ${climb.gems.length} gems. Space or a tap to climb again`,
      WIDTH / 2,
      banner.y + 42,
      small,
    );
  }
  stick.draw(g.ctx);
});

const render = (alpha: number, dt: number): void => {
  screenTweens.update(dt);
  camera.update(dt);
  renderer.render(alpha, dt);
  report();
};

const loop = createLoop({ step: LEVEL.step, update, render, afterFrame: () => input.endFrame() });
pauseOnHidden(loop);
hud.dataset.ready = "1";
loop.start();

if (__KARNI_GAME_DEV__) {
  // A development handle, dropped from every build by the preset's flag.
  (window as unknown as Record<string, unknown>).__crateClimb = { loop, camera, renderer };
}
