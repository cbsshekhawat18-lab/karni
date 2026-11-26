---
description: "Scenes in @karni/game/scenes: a scene stack with push, pop and replace, overlays that pause what is below, fade transitions that respect reduced motion, an entity list with tags and safe removal, and a store for settings and progress on the save layer."
---

# Scenes (@karni/game/scenes)

!!! warning "Experimental"
    `@karni/game/scenes` is [experimental](stability.md#experimental-names): a name
    or an option may change in a minor release, with a CHANGELOG entry.

Every game has screens: a title, a level, a pause menu, a game over. A plain canvas game
ends up writing the same switch between them. `@karni/game/scenes` is that switch: a stack of
scenes with the hooks a scene needs, overlays, a fade between scenes, a small entity list and
a store for settings and progress.

It has no dependency, no Node API and no global. A scene gets the loop, the input, the audio,
the save, the portal and the client from the stack, so it imports none of them and a test can
hand it fakes. The entry point is small (a gzip budget of 2600 bytes, tested) and a game
bundles only what it imports.

```ts
import { createSceneStack, createEntityList, createStore, drawCover } from "@karni/game/scenes";
```

The drawing and the player's menus are other pieces: scenes decide what runs, the
[game UI](game-ui.md) is what the player reads and presses.

## A scene

```ts
import type { Scene } from "@karni/game/scenes";

export function createTitleScene(): Scene {
  return {
    name: "title",
    enter({ services, stack }) {
      // The scene is now the top of the stack.
    },
    exit() {},
    update({ services, stack }, dt) {
      if (services.input?.pressed("jump")) stack.replace(createPlayScene(), { duration: 0.3 });
    },
    draw({ services }, alpha) {},
  };
}
```

Every hook is optional. Make scenes with a function, so each push gets its own state.

| Hook | When it runs |
|---|---|
| `enter(context)` | The scene was pushed or swapped in, or the stack made it the top. |
| `exit(context)` | The scene left the stack. |
| `pause(context)` | Something was pushed on top of it. |
| `resume(context)` | What was on top of it left. |
| `update(context, dt)` | Once per `stack.update(dt)` while the scene runs. With the loop's fixed step, `dt` is the step. |
| `draw(context, alpha)` | Once per `stack.draw(alpha)` while the scene shows. `alpha` is the leftover fraction of a step. |

A hook that throws is reported to `onError` (default `console.error`) and the stack goes on, as
the loop does for a frame that throws.

`context` has `services`, `stack` and `data`, the value the scene was pushed with:

```ts
stack.push(createLevelScene(), { data: { level: 4 } });   // enter({ data }) reads data.level
```

## The stack

```ts
import { createLoop, createInput } from "@karni/game";
import { createSceneStack, type SceneServices } from "@karni/game/scenes";

interface Services extends SceneServices {
  context: CanvasRenderingContext2D;   // the game's own services go beside the package's
}

const stack = createSceneStack<Services>({ services: { loop, input, audio, context } });
const loop = createLoop({
  step: 1 / 120,
  update: (dt) => stack.update(dt),
  render: (alpha) => stack.draw(alpha),
});
stack.push(createTitleScene());
```

`SceneServices` lists `loop`, `input`, `audio`, `save`, `portal` and `client`, each optional so
a test supplies only what a scene reads. A game extends it with its own services and passes the
type, so scenes stay typed and import no global.

| Call | Does |
|---|---|
| `push(scene, options?)` | Put a scene on top. |
| `pop(options?)` | Remove the top scene. |
| `replace(scene, options?)` | Swap the top scene. |
| `clear()` | Remove every scene, top first. |
| `top`, `depth`, `names`, `has(name)` | Look at the stack. |
| `on("change", listener)` | Called after a push, pop or replace took effect. |

A change asked for inside a hook is applied after the update that asked for it, in order, so a
scene may call `stack.replace` from its own `update`.

## Overlays

An overlay is drawn over the scene below it. By default it also pauses that scene: the scene is
drawn and not updated.

```ts
stack.push(createPauseScene(), { overlay: true });
```

A scene may set `overlay: true` itself. `pauses: false` keeps the scene below updating, for an
overlay that is only a layer (a HUD or a tutorial hint). A full scene covers the one below, which
is neither updated nor drawn. When the loop itself is paused (the pause menu of the kit does
that), no scene updates and the scenes still draw.

## Transitions

```ts
stack.replace(createPlayScene(), { duration: 0.4 });
```

With a `duration` in seconds the change fades out for half of it, swaps at the middle and fades
in for the other half. The scenes stand still while the screen fades out. `stack.cover` runs from
0 to 1 and back, and `drawCover(context, stack.cover, width, height, color)` paints it. Put it
last in the render. A change asked for during a fade waits and runs after it.

Reduced motion makes every transition instant. The default reads the browser's
`prefers-reduced-motion`. A game with a setting passes its own:

```ts
createSceneStack({ services, reducedMotion: () => settings.state.reducedMotion });
```

A transition counts update time, so a paused loop holds it.

## The entity list

```ts
const enemies = createEntityList<Enemy>();
enemies.add(slime, "enemy");
enemies.add(coin, "pickup");

enemies.each((thing) => {
  if (thing.dead) enemies.remove(thing);       // safe in the middle of the loop
});
enemies.byTag("pickup");                        // a copy, in the order they were added
```

An ordered list with tags. An entity removed during `each` and not yet visited is skipped, and
one added during `each` waits for the next loop. `removeTagged`, `removeWhere`, `eachTagged`,
`has`, `tagged`, `size` and `clear` are there too. It holds objects and has no components: the
evidence of the games shows lists of plain objects, and the list stays that.

## The store

```ts
import { createSave, createStorage } from "@karni/game";
import { createStore } from "@karni/game/scenes";

const storage = createStorage({ namespace: "block-hopper" });
const progress = createStore({
  save: createSave({ storage, key: "progress", version: 1, defaults: () => ({ best: 0, stars: {} }) }),
});

progress.set({ best: 120 });
progress.update((draft) => { draft.stars["level-1"] = 3; });
progress.subscribe((state, previous) => { /* redraw the HUD */ });
```

A store keeps state in a [save](game-client.md#saves-on-the-device), so versions, migrations, the corrupt-save
rule and the storage fallback are the save layer's. It notifies subscribers on every change, waits
250 ms after the last change before it writes (`debounceMs`, 0 writes at once) and writes again
when the page is hidden or closed. `loaded.status` says how the save loaded, `reset()` goes back
to the defaults and `flush()` writes now. The settings of the [game UI](game-ui.md) are a store.

## Testing a scene

A scene is a plain object, so a test pushes it on a stack with fake services and calls
`stack.update(dt)`. The tests of this entry point do exactly that.

## Escape hatches

- `reducedMotion` replaces the check for reduced motion.
- `onError` replaces the report of a hook that threw.
- `overlay` and `pauses` change how a scene covers the one below.
- The services are your own type, and the stack never reads a global.
- A game on Phaser, PixiJS or React Three Fiber keeps the scenes of its engine. This entry point
  is for plain canvas.
