import { describe, expect, it } from "vitest";
import {
  createClimb,
  stepClimb,
  type Climb,
  type ClimbEvent,
  type ClimbInput,
} from "../example/crate-climb/src/level";

const idle: ClimbInput = { left: false, right: false, jump: false, down: false };

/** Run `seconds` of steps with one input (a jump only on the first step), and keep every event. */
function hold(climb: Climb, input: Partial<ClimbInput>, seconds: number): ClimbEvent[] {
  const events: ClimbEvent[] = [];
  const steps = Math.round(seconds * 120);
  for (let n = 0; n < steps; n += 1) {
    events.push(...stepClimb(climb, { ...idle, ...input, jump: n === 0 && !!input.jump }));
  }
  return events;
}

/** Put the climber somewhere, standing still. */
function place(climb: Climb, x: number, y: number): void {
  Object.assign(climb.player, { x, y, vy: 0, grounded: false });
  hold(climb, {}, 0.2);
}

const types = (events: ClimbEvent[]) => events.map((event) => event.type);

describe("Crate Climb's rules", () => {
  it("runs along the floor, takes the gems on the way, and stops at a crate", () => {
    const climb = createClimb();
    const events = hold(climb, { right: true }, 3);
    expect(climb.taken).toBe(2);
    expect(types(events).filter((type) => type === "gem")).toHaveLength(2);
    expect(climb.player.x).toBe(420 - 14);
    expect(climb.player.grounded).toBe(true);
  });

  it("jumps onto a crate", () => {
    const climb = createClimb();
    place(climb, 380, 480);
    hold(climb, { right: true, jump: true }, 0.3);
    hold(climb, {}, 0.5);
    expect(climb.player.x).toBeGreaterThan(420);
    expect(climb.player.y).toBe(468 - 20);
    expect(climb.player.grounded).toBe(true);
  });

  it("jumps up through a one-way ledge, stands on it, and drops back through it", () => {
    const climb = createClimb();
    place(climb, 560, 480);
    const events = hold(climb, { jump: true }, 1);
    expect(climb.player.y).toBe(420 - 20);
    expect(types(events)).toEqual(["jump", "gem", "land"]);
    hold(climb, { down: true }, 0.6);
    expect(climb.player.y).toBe(500 - 20);
  });

  it("lands hard after a long fall", () => {
    const climb = createClimb();
    place(climb, 690, 330);
    expect(climb.player.y).toBe(350 - 20);
    const events = hold(climb, { down: true }, 0.8);
    const land = events.find((event) => event.type === "land");
    expect(land).toMatchObject({ type: "land", hard: true });
  });

  it("brings a fallen climber back at the start, then at the checkpoint once passed", () => {
    const climb = createClimb();
    place(climb, 740, 480);
    const fell = hold(climb, { right: true }, 1);
    expect(types(fell)).toContain("respawn");
    place(climb, 860, 380);
    expect(climb.spawn).toEqual({ x: 850, y: 380 });
    place(climb, 790, 300);
    const again = hold(climb, {}, 1);
    expect(types(again)).toContain("respawn");
    expect(climb.player.x).toBe(850);
    expect(climb.player.y).toBe(380);
  });

  it("ends at the flag, once, and then ignores the controls", () => {
    const climb = createClimb();
    place(climb, 1460, 180);
    const events = hold(climb, { right: true }, 1.5);
    expect(types(events).filter((type) => type === "goal")).toHaveLength(1);
    expect(climb.done).toBe(true);
    const x = climb.player.x;
    hold(climb, { left: true, jump: true }, 0.5);
    expect(climb.player.x).toBe(x);
  });

  it("plays the same run the same way twice", () => {
    const run = (): Climb => {
      const climb = createClimb();
      hold(climb, { right: true }, 0.5);
      hold(climb, { right: true, jump: true }, 0.7);
      hold(climb, { left: true }, 0.3);
      return climb;
    };
    const a = run();
    const b = run();
    expect(a.player).toEqual(b.player);
    expect(a.taken).toBe(b.taken);
  });

  it("can be climbed to the top: every hop of the route lands", () => {
    // From where the climber stands to the solid it must land on: [start x, start top, target].
    const route: [number, number, { x: number; y: number; w: number }][] = [
      [380, 500, { x: 420, y: 468, w: 32 }],
      [425, 468, { x: 452, y: 436, w: 32 }],
      [462, 436, { x: 520, y: 420, w: 110 }],
      [600, 420, { x: 680, y: 350, w: 100 }],
      [760, 350, { x: 850, y: 400, w: 100 }],
      [920, 400, { x: 980, y: 340, w: 110 }],
      [1070, 340, { x: 1140, y: 280, w: 110 }],
      [1230, 280, { x: 1300, y: 220, w: 100 }],
      [1380, 220, { x: 1440, y: 200, w: 160 }],
    ];
    for (const [x, top, target] of route) {
      let made = false;
      // Hold right for a while after the jump: some time between 0.05 s and 1 s must work.
      for (let held = 0.05; held <= 1 && !made; held += 0.05) {
        const climb = createClimb();
        place(climb, x, top - 20);
        hold(climb, { right: true, jump: true }, held);
        hold(climb, {}, 1);
        const p = climb.player;
        made =
          p.grounded && p.y === target.y - 20 && p.x + p.w > target.x && p.x < target.x + target.w;
      }
      expect(made, `the hop from x ${x} to the solid at ${target.x}, ${target.y}`).toBe(true);
    }
    const climb = createClimb();
    place(climb, 1450, 180);
    expect(types(hold(climb, { right: true }, 2))).toContain("goal");
  });
});
