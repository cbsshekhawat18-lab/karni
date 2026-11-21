import { describe, expect, it, vi } from "vitest";
import {
  boxCircleOverlap,
  boxContact,
  boxesOverlap,
  castRay,
  circleBoxContact,
  circleContact,
  circlesOverlap,
  createContact,
  createHit,
  createMove,
  createTriggers,
  moveBox,
  pointInBox,
  pointInCircle,
  segmentBox,
  segmentCircle,
  sweepBox,
  sweepCircle,
  type Box,
  type Circle,
  type Solid,
  type SolidQuery,
} from "../src/collide";

describe("overlap tests", () => {
  it("does not count touching edges as overlap", () => {
    const floor = { x: 0, y: 100, w: 200, h: 20 };
    expect(boxesOverlap({ x: 10, y: 80, w: 20, h: 20 }, floor)).toBe(false);
    expect(boxesOverlap({ x: 10, y: 81, w: 20, h: 20 }, floor)).toBe(true);
    expect(circlesOverlap({ x: 0, y: 0, r: 5 }, { x: 10, y: 0, r: 5 })).toBe(false);
    expect(circlesOverlap({ x: 0, y: 0, r: 5 }, { x: 9, y: 0, r: 5 })).toBe(true);
    expect(boxCircleOverlap(floor, { x: -3, y: 97, r: 4 })).toBe(false);
    expect(boxCircleOverlap(floor, { x: -2, y: 98, r: 4 })).toBe(true);
    expect(pointInBox(0, 100, floor)).toBe(true);
    expect(pointInBox(200, 100, floor)).toBe(false);
    expect(pointInCircle(3, 4, { x: 0, y: 0, r: 5 })).toBe(false);
  });

  it("gives the shortest push out of a box or a circle", () => {
    const contact = createContact();
    expect(
      boxContact({ x: 95, y: 10, w: 10, h: 10 }, { x: 100, y: 0, w: 50, h: 50 }, contact),
    ).toBe(true);
    expect(contact).toEqual({ nx: -1, ny: 0, depth: 5 });
    boxContact({ x: 110, y: 45, w: 10, h: 10 }, { x: 100, y: 0, w: 50, h: 50 }, contact);
    expect(contact).toEqual({ nx: 0, ny: 1, depth: 5 });
    expect(boxContact({ x: 0, y: 0, w: 1, h: 1 }, { x: 5, y: 5, w: 1, h: 1 }, contact)).toBe(false);

    expect(circleContact({ x: 8, y: 0, r: 5 }, { x: 0, y: 0, r: 5 }, contact)).toBe(true);
    expect(contact).toEqual({ nx: 1, ny: 0, depth: 2 });
    circleContact({ x: 0, y: 0, r: 1 }, { x: 0, y: 0, r: 1 }, contact);
    expect(contact).toEqual({ nx: 0, ny: -1, depth: 2 });

    const wall = { x: 0, y: 0, w: 10, h: 100 };
    expect(circleBoxContact({ x: 13, y: 50, r: 4 }, wall, contact)).toBe(true);
    expect(contact.nx).toBeCloseTo(1);
    expect(contact.depth).toBeCloseTo(1);
    // The centre inside the box: out through the nearest side.
    circleBoxContact({ x: 8, y: 50, r: 4 }, wall, contact);
    expect(contact).toEqual({ nx: 1, ny: 0, depth: 6 });
    expect(circleBoxContact({ x: 20, y: 50, r: 4 }, wall, contact)).toBe(false);
  });
});

describe("segment and sweep tests", () => {
  const wall: Box = { x: 100, y: 0, w: 4, h: 100 };

  it("finds where a segment enters a box, and its normal", () => {
    const hit = createHit();
    expect(segmentBox(0, 50, 200, 0, wall, hit)).toBe(true);
    expect(hit).toEqual({ time: 0.5, x: 100, y: 50, nx: -1, ny: 0 });
    expect(segmentBox(0, 50, 50, 0, wall, hit)).toBe(false);
    expect(segmentBox(0, 150, 200, 0, wall)).toBe(false);
    // From inside: a hit at once, with no normal.
    expect(segmentBox(102, 50, 10, 0, wall, hit)).toBe(true);
    expect(hit).toMatchObject({ time: 0, nx: 0, ny: 0 });
    // Along an edge is no touch.
    expect(segmentBox(100, -10, 0, 200, wall)).toBe(false);
  });

  it("stops a fast box at a thin wall instead of passing through it", () => {
    const hit = createHit();
    const bullet = { x: 0, y: 40, w: 8, h: 8 };
    // 1000 units in one step, across a wall 4 wide.
    expect(boxesOverlap({ ...bullet, x: 1000 }, wall)).toBe(false);
    expect(sweepBox(bullet, 1000, 0, wall, hit)).toBe(true);
    expect(hit.x).toBeCloseTo(92);
    expect(hit.time).toBeCloseTo(0.092);
    expect([hit.nx, hit.ny]).toEqual([-1, 0]);
    // Moving away from a wall it touches is no hit; moving into it is, at once.
    const touching = { x: 92, y: 40, w: 8, h: 8 };
    expect(sweepBox(touching, -50, 0, wall)).toBe(false);
    expect(sweepBox(touching, 50, 0, wall, hit)).toBe(true);
    expect(hit.time).toBe(0);
    // Sliding along it is no hit either.
    expect(sweepBox(touching, 0, 50, wall)).toBe(false);
  });

  it("sweeps circles and casts segments at them", () => {
    const hit = createHit();
    const post: Circle = { x: 100, y: 0, r: 10 };
    expect(segmentCircle(0, 0, 200, 0, post, hit)).toBe(true);
    expect(hit).toMatchObject({ time: 0.45, x: 90, y: 0, nx: -1, ny: 0 });
    expect(segmentCircle(0, 20, 200, 0, post)).toBe(false);
    expect(segmentCircle(0, 0, 0, 0, post)).toBe(false);
    expect(sweepCircle({ x: 0, y: 0, r: 5 }, 200, 0, post, hit)).toBe(true);
    expect(hit.x).toBeCloseTo(85);
    expect(hit.nx).toBeCloseTo(-1);
    // Touching and moving away is no hit.
    expect(sweepCircle({ x: 85, y: 0, r: 5 }, -10, 0, post)).toBe(false);
  });

  it("casts a ray at the nearest of many boxes", () => {
    const hit = createHit();
    const boxes = [
      { name: "far", x: 300, y: 0, w: 10, h: 100 },
      { name: "near", x: 150, y: 0, w: 10, h: 100 },
      { name: "above", x: 50, y: -100, w: 10, h: 50 },
    ];
    expect(castRay(0, 50, 1000, 0, boxes, hit)?.name).toBe("near");
    expect(hit.x).toBe(150);
    expect(castRay(0, 50, 1000, 0, boxes, hit, (box) => box.name !== "near")?.name).toBe("far");
    expect(castRay(0, 50, -1000, 0, boxes, hit)).toBeNull();
  });
});

describe("moveBox", () => {
  const level: Solid[] = [
    { x: 0, y: 200, w: 400, h: 20 },
    { x: 300, y: 100, w: 20, h: 100 },
    { x: 100, y: 150, w: 80, h: 6, oneWay: true },
  ];

  it("lands on the floor and slides along it", () => {
    const body = { x: 20, y: 150, w: 16, h: 16 };
    const move = moveBox(body, 30, 100, level);
    expect(body).toMatchObject({ x: 50, y: 184 });
    expect(move).toMatchObject({ dx: 30, dy: 34, bottom: true, top: false, hitY: level[0] });
    expect(moveBox(body, 10, 0, level).bottom).toBe(false);
    expect(body.x).toBe(60);
  });

  it("stops at a wall and keeps the fall", () => {
    const body = { x: 270, y: 120, w: 16, h: 16 };
    const move = moveBox(body, 40, 10, level);
    expect(body).toMatchObject({ x: 284, y: 130 });
    expect(move).toMatchObject({ right: true, left: false, hitX: level[1], dy: 10 });
    // Pressing into the wall: no movement on x, the contact is reported.
    expect(moveBox(body, 5, 0, level)).toMatchObject({ dx: 0, right: true });
    expect(moveBox(body, -5, 0, level)).toMatchObject({ dx: -5, left: false });
  });

  it("never passes through a solid however far one step moves", () => {
    const body = { x: 0, y: 0, w: 10, h: 10 };
    moveBox(body, 0, 100000, level);
    expect(body.y).toBe(190);
    const sideways = { x: 0, y: 150, w: 10, h: 10 };
    moveBox(sideways, 100000, 0, level);
    expect(sideways.x).toBe(290);
  });

  it("passes up through a one-way ledge, lands on it, and drops through on request", () => {
    const body = { x: 120, y: 170, w: 16, h: 16 };
    expect(moveBox(body, 0, -40, level).top).toBe(false);
    expect(body.y).toBe(130);
    expect(moveBox(body, 0, 30, level).bottom).toBe(true);
    expect(body.y).toBe(134);
    // A ledge never blocks sideways.
    expect(moveBox(body, 100, 0, level).right).toBe(false);
    body.x = 120;
    expect(moveBox(body, 0, 10, level, { dropThrough: true }).bottom).toBe(false);
    expect(body.y).toBe(144);
    // Below the ledge's top it no longer holds: the body falls on to the floor.
    expect(moveBox(body, 0, 100, level).hitY).toBe(level[0]);
  });

  it("walks out of a solid it is already inside", () => {
    const body = { x: 305, y: 150, w: 10, h: 10 };
    const move = moveBox(body, -20, 0, level);
    expect(move.left).toBe(false);
    expect(body.x).toBe(285);
  });

  it("asks a broad phase of the game's own for the solids near the move", () => {
    const seen: Box[] = [];
    const query: SolidQuery<Solid> = (area, visit) => {
      seen.push({ ...area });
      for (const solid of level) if (boxesOverlap(area, solid)) visit(solid);
    };
    const body = { x: 20, y: 150, w: 16, h: 16 };
    expect(moveBox(body, 30, 100, query).bottom).toBe(true);
    expect(seen).toEqual([
      { x: 20, y: 150, w: 46, h: 16 },
      { x: 50, y: 150, w: 16, h: 116 },
    ]);
  });

  it("skips filtered solids and the body itself, and writes into a result of the caller's", () => {
    const self = { x: 20, y: 150, w: 16, h: 16 };
    const filter = vi.fn((solid: Solid) => solid !== level[0]);
    const out = createMove();
    const move = moveBox(self, 0, 100, [self, ...level], { filter }, out);
    expect(move).toBe(out);
    expect(self.y).toBe(250);
    expect(filter).toHaveBeenCalled();
    // A move with no result passed shares one: the next call overwrites it.
    const first = moveBox({ x: 0, y: 0, w: 1, h: 1 }, 1, 0, []);
    const second = moveBox({ x: 0, y: 0, w: 1, h: 1 }, 2, 0, []);
    expect(first).toBe(second);
    expect(first.dx).toBe(2);
    // Not a number moves nothing.
    expect(moveBox(self, Number.NaN, Number.POSITIVE_INFINITY, level)).toMatchObject({
      dx: 0,
      dy: 0,
    });
  });
});

describe("createTriggers", () => {
  it("reports a body coming in once, staying, and going out", () => {
    const log: string[] = [];
    const triggers = createTriggers<Box & { id: string }, Box>({
      enter: (zone) => log.push(`enter ${zone.id}`),
      stay: (zone) => log.push(`stay ${zone.id}`),
      exit: (zone) => log.push(`exit ${zone.id}`),
    });
    const water = { id: "water", x: 100, y: 0, w: 50, h: 50 };
    triggers.add(water);
    triggers.add(water);
    const player = { x: 0, y: 10, w: 10, h: 10 };
    triggers.update(player);
    player.x = 110;
    triggers.update(player);
    triggers.update(player);
    expect(triggers.inside(water, player)).toBe(true);
    player.x = 300;
    triggers.update([player]);
    expect(log).toEqual(["enter water", "stay water", "exit water"]);
    expect(triggers.zones).toHaveLength(1);
  });

  it("lets a handler remove its zone: a coin is taken once", () => {
    const taken: string[] = [];
    const triggers = createTriggers<Box & { id: string }, Box>({
      enter: (zone) => {
        taken.push(zone.id);
        triggers.remove(zone);
      },
    });
    const coins = ["a", "b", "c"].map((id, i) => ({ id, x: i * 20, y: 0, w: 10, h: 10 }));
    for (const coin of coins) triggers.add(coin);
    const player = { x: 0, y: 0, w: 30, h: 10 };
    triggers.update(player);
    triggers.update(player);
    expect(taken).toEqual(["a", "b"]);
    expect(triggers.zones.map((zone) => zone.id)).toEqual(["c"]);
    expect(triggers.has(coins[0] as Box & { id: string })).toBe(false);
  });

  it("tracks several bodies apart, forgets one, and takes a test of the game's own", () => {
    const exits: string[] = [];
    const triggers = createTriggers<Circle, Circle & { id: string }>({
      overlaps: circlesOverlap,
      exit: (_zone, body) => exits.push(body.id),
    });
    const aura = { x: 0, y: 0, r: 10 };
    triggers.add(aura);
    const a = { id: "a", x: 5, y: 0, r: 1 };
    const b = { id: "b", x: 50, y: 0, r: 1 };
    triggers.update([a, b]);
    expect([triggers.inside(aura, a), triggers.inside(aura, b)]).toEqual([true, false]);
    triggers.forget(a);
    expect(triggers.inside(aura, a)).toBe(false);
    triggers.update([a]);
    triggers.remove(aura);
    expect(exits).toEqual(["a"]);
    triggers.clear();
    expect(triggers.zones).toHaveLength(0);
  });
});
