---
description: "@karni/game/collide (experimental): kinematic collision for 2D browser games. Axis-aligned boxes and circles, overlap and contact tests, segment and sweep tests, a ray cast, a box mover that slides against solid boxes with one-way ledges, and trigger zones. No rigid-body physics."
---

# Collision (@karni/game/collide)

!!! warning "Experimental"
    `@karni/game/collide` is [experimental](stability.md#experimental-names):
    a name or an option may change in a minor release, with a CHANGELOG entry.

`@karni/game/collide` is the collision a 2D game writes by hand: do two
things touch, where does a shot land, and how does a body move through a
level without passing through a wall. It works on plain numbers, with no
page, no clock and no random source, so the game's rules can use it and a
test can run it headless. It pairs with [drawing](game-draw.md) but needs
nothing from it.

It is kinematic: the game moves its things, and collide answers questions
and stops a box at walls. There are no bodies with mass, no stacking, no
joints and no rotation. A game that needs them steps a physics library
inside the loop's fixed step at the loop's time scale.

## Shapes

A box is any object with `x`, `y` (its top-left corner), `w` and `h`. A
circle is any object with `x`, `y` (its centre) and `r`. An entity is
passed as itself: there is no wrapper to keep in step.

## Overlap and contact

| Call | Answers |
|---|---|
| `boxesOverlap(a, b)`, `circlesOverlap(a, b)`, `boxCircleOverlap(box, circle)` | do they overlap |
| `pointInBox(x, y, box)`, `pointInCircle(x, y, circle)` | is the point inside |
| `boxContact(a, b, out)`, `circleContact(a, b, out)`, `circleBoxContact(circle, box, out)` | do they overlap, and the shortest push of the first out of the second |

Touching edges do not overlap: a box standing on a floor is not inside it.
A contact (`createContact()`) holds the push as a unit normal (`nx`, `ny`)
and a `depth`, enough to separate two enemies or bounce a ball off a brick:

```ts
const contact = createContact();
if (circleBoxContact(ball, brick, contact)) {
  ball.x += contact.nx * contact.depth;
  ball.y += contact.ny * contact.depth;
  if (contact.nx !== 0) ball.vx = -ball.vx;
  else ball.vy = -ball.vy;
}
```

## Segments, sweeps and rays

A test between frames misses a fast thing: a bullet moving 30 units a step
passes a wall 4 units thick without ever overlapping it. Sweeps look at the
whole move.

| Call | Finds |
|---|---|
| `segmentBox(x, y, dx, dy, box, out)`, `segmentCircle(...)` | where a segment from x, y along dx, dy first touches |
| `sweepBox(a, dx, dy, b, out)` | where box `a`, moving by dx, dy, first touches box `b` |
| `sweepCircle(a, dx, dy, b, out)` | the same for two circles |
| `castRay(x, y, dx, dy, boxes, out, filter)` | the nearest of many boxes a segment touches, or null: line of sight, a laser |

A hit (`createHit()`) holds `time` (the share of the move made before the
touch, 0 to 1), the point `x`, `y` (the moving shape's position for a
sweep) and the surface normal `nx`, `ny`. A move that starts inside gives a
hit at time 0 with no normal. Moving away from a side it touches, or
sliding along it, is no hit.

## The box mover

`moveBox(body, dx, dy, solids, options, out)` moves a box through solid
boxes: first along x, then along y, each axis stopped at the first solid in
the way. That is the movement of a platformer or a top-down game:

- It slides along walls and floors, and a body pressing into a corner is
  stopped on both sides.
- It never passes through a solid, however far one step moves.
- A solid with `oneWay: true` stops it only from above: a ledge a body jumps
  up through and lands on. `dropThrough: true` falls through ledges for that
  move (down pressed on a ledge). A ledge never blocks sideways.
- A solid it already overlaps does not stop it, so a body pushed inside one
  walks out. The body itself in the list is skipped.
- `filter(solid)` ignores solids (a team's own walls).

```ts
const moved = createMove(); // made once, reused every step
const options = { dropThrough: false };

function step(player: Player, input: Input, dt: number): void {
  player.vy += GRAVITY * dt;
  options.dropThrough = input.down;
  moveBox(player, input.dir * SPEED * dt, player.vy * dt, level.solids, options, moved);
  player.grounded = moved.bottom;
  if (moved.bottom || moved.top) player.vy = 0;
}
```

The body's `x` and `y` change in place. The result says how far it moved
(`dx`, `dy`), which sides were stopped (`left`, `right`, `top`, `bottom`)
and the solid that stopped it on each axis (`hitX`, `hitY`). Without `out`
the result is one object shared by every call: copy what you keep.

Slopes and moving platforms are not in the mover. A level with slopes keeps
them as data and moves along them in its own rules.

### Many solids

`solids` is an array, checked whole. For a level of a few hundred boxes
that is fast: the browser benchmark moves 50 bodies among 200 solids every
frame inside its frame budget. A bigger level passes a query of its own
instead of the array, a grid or a list per room:

```ts
const query: SolidQuery<Solid> = (area, visit) => {
  for (const solid of grid.near(area)) visit(solid);
};
moveBox(player, dx, dy, query);
```

`area` is the box the move sweeps through. Karni keeps no broad phase of its
own until games show they need one.

## Trigger zones

`createTriggers({ enter, stay, exit, overlaps })` reports bodies coming into
zones and going out of them: coins, checkpoints, a goal, water. Each change
is reported once, so a coin is taken once however long the player stands on
it.

```ts
const pickups = createTriggers<Gem, Player>({
  overlaps: (gem, player) => boxCircleOverlap(player, gem), // gems are circles
  enter(gem) {
    score += 1;
    pickups.remove(gem); // safe inside a handler
  },
});
for (const gem of level.gems) pickups.add(gem);
// every step:
pickups.update(player); // or an array of bodies
```

- Zones are boxes by default, and `overlaps` tests anything else.
- `remove(zone)` is safe inside a handler, and bodies still inside get
  `exit`. `forget(body)` drops a removed body without `exit`.
- `inside(zone, body)` tells the state of the last update.

## Performance

The tests, the sweeps, the mover and the triggers' updates make no garbage
per step: results go into objects the game makes once (`createHit`,
`createContact`, `createMove`). The entry point has a gzip size budget of
2.3 KB, checked by a test on a minified build, and a game bundles only what
it imports.

## The example

`modules/karni-game/ui/example/crate-climb/src/level.ts` is a level on
these pieces: walls and crates, one-way ledges, gems as circle zones, a
checkpoint and a flag as box zones, and a hard landing found from the
speed of the fall. Its tests show that each hop of the route lands, and
Block Hopper (`example/block-hopper/src/core.ts`) moves on one-way
platforms with the same mover.

## What it does not do

- No rigid-body physics: no mass, restitution, friction, stacking, joints
  or rotation. Use a physics library inside the fixed step.
- No polygons or rotated boxes: circles and axis-aligned boxes only.
- No slopes or moving platforms in the mover.
- No broad phase: pass a query of the game's own when a level needs one.
