---
description: "The game UI kit in @karni/game/ui (experimental): a DOM layer above the canvas with settings, key remapping, pause, dialogs, confirm, toasts, touch buttons, a boot failure screen, a dev overlay and a strings table, with keyboard focus, screen reader labels and light and dark colours."
---

# Game UI (@karni/game/ui)

!!! warning "Experimental"
    `@karni/game/ui` is [experimental](stability.md#experimental-names): a name
    or an option may change in a minor release, with a CHANGELOG entry.

The menus of a game are DOM elements above the canvas, not buttons drawn on it. The browser
then lays out the text, moves the focus and reads it aloud, and the kit adds nothing for that.
`@karni/game/ui` is the set of those elements that every game needs: settings, a pause menu,
dialogs, toasts, touch buttons, a screen for a game that cannot start and a small overlay for
development.

It has no dependency. Every function is tree-shaken, and the whole entry has a gzip budget of
9800 bytes (tested). A game that only opens a dialog bundles about half of that.

```ts
import { createUi, openPause, openSettings } from "@karni/game/ui";
```

## The layer

```ts
const ui = createUi({ input });            // appended to document.body
const ui = createUi({ host: stageElement, theme: "dark", strings: { resume: "Weiter" } });
```

`createUi` adds one positioned layer over the host and the kit's stylesheet (once). The layer
does not catch pointer events, so the canvas below still gets taps. Only the panels, dialogs and
buttons do. A React game passes the element of a ref as `host`.

| Option | Does |
|---|---|
| `host` | The element the layer covers. Default `document.body`. |
| `theme` | `"auto"` follows the system, or `"light"` and `"dark"` force one. |
| `strings` | Replaces any of the kit's words. |
| `input` | Lets go of held keys when a dialog opens, so nothing sticks while it is up. |
| `styles` | `false` leaves the stylesheet to you. The classes are `kg-` and the colours are custom properties on `.kg-ui` (`--kg-bg`, `--kg-fg`, `--kg-accent`, ...). |

## Dialogs, confirm and screens

```ts
const dialog = ui.dialog({
  title: "Level complete",
  body: "You collected 12 coins.",
  actions: [
    { id: "again", label: "Play again" },
    { id: "next", label: "Next level", primary: true },
  ],
});
const choice = await dialog.result;          // "again", "next", or null when dismissed

if (await ui.confirm({ title: "Delete the save?", danger: true, confirmLabel: "Delete" })) { }
```

A dialog is `role="dialog"` with `aria-modal` and a label from its title. It focuses its primary
action, keeps Tab inside, closes on Escape and on a click outside (turn that off with
`dismissable: false`), makes everything behind it inert and gives focus back to what had it.
Keys typed in a dialog never reach the game's input. A second dialog stacks on the first and
only the top one is live. `confirm` starts a destructive question on Cancel.

`ui.screen({ title, text, actions })` is a panel that is part of the page, such as a title screen.
It does not trap focus and it lets taps through to the canvas around it.

## Toasts

```ts
ui.toast("Saved");
ui.toast("Could not reach the server", { kind: "error" });
```

A toast has the role `status`, an error has `alert`, so a screen reader announces it. It leaves
after four seconds (eight for an error, `durationMs: 0` keeps it) and has a Dismiss button. Three
show at most.

## Settings

```ts
import { applySettings, createSettings, openSettings } from "@karni/game/ui";

const settings = createSettings({ storage });            // its own save, key "settings"
applySettings({ store: settings, audio, input, ui });   // the game follows the settings, now and later

openSettings(ui, {
  store: settings,
  controls: [
    { action: "jump", label: "Jump", codes: ["Space", "ArrowUp", "Pointer"] },
    { action: "left", label: "Left", codes: ["ArrowLeft", "KeyA"] },
  ],
});
```

The dialog has volume sliders for master, music and effects, a mute switch, reduced motion, the
colour-safe palette switch and a controls list. Each slider has a label and a spoken value, each
switch has a label and a hint.

`createSettings` returns a [store](game-scenes.md#the-store) on a save of its own, so a game's
progress save is untouched. `applySettings` sets the audio volumes and the player's mute, the
remapped bindings on the input (`input.bind`), the palette and reduced motion on the layer. Reduced
motion starts from the system's setting. A game reads `settings.state.reducedMotion` in its own
effects and passes the same check to the scene stack.

**Remapping.** Choose a control and press the key you want. Escape cancels. The new key replaces
the control's keyboard keys and keeps its pointer and stick codes. A key already used by another
control is taken from it, and a live region says so. "Reset controls" goes back to the codes you
gave as `codes`.

**Colour-safe.** The switch sets `data-kg-palette="safe"` on the layer, which changes the kit's
accent and error colours to a blue and a vermillion that stay apart for the common kinds of
colour blindness. `COLOUR_SAFE` is the same set of eight colours as data, for the game's own
drawing: `settings.state.colourSafe ? COLOUR_SAFE.blue : "#4a90d9"`.

## Pause

```ts
const menu = openPause(ui, {
  loop,
  onSettings: () => openSettings(ui, { store: settings }),
  onQuit: () => stack.replace(createTitleScene()),
});
```

The menu holds Resume, an optional Settings and an optional Quit that asks first. It pauses the
loop with the reason `"menu"` while it is open, so audio and the game stand still, and resumes it
when it closes. Settings opens on top of it and the menu stays. Put it in a scene pushed with
`overlay: true` ([the pause scene of the example](https://github.com/cbsshekhawat18-lab/karni/blob/main/modules/karni-game/ui/example/block-hopper/src/scenes/pause.ts)).

## Touch buttons

```ts
createTouchButtons(ui, input, [
  { action: "left", label: "Left", side: "left" },
  { action: "jump", label: "Jump", side: "right" },
]);
```

Real buttons that press and release the input's action while a finger is down, so one binding
serves the keyboard, the stick and the screen. They show on a touch screen (a coarse pointer, or
at the first touch). `show: "always"` and `"never"` force it. A press on a button never reaches
the canvas, Enter and Space press them from the keyboard, and each is at least 64 pixels wide.

## The boot failure screen

```ts
import { guardBoot, showBootFailure } from "@karni/game/ui";

void guardBoot(async () => {
  await loadEverything();
  loop.start();
});
```

When the start throws (no WebGL, a failed load, a blocked storage the game cannot do without),
the player reads "The game could not start" with a Try again button and, under Details, the error
for a bug report. Try again runs the start again, or reloads the page with `showBootFailure` and
no `onRetry`. The screen needs nothing else of the kit, so it works when everything else did
not. The title, the message and every other word come from the strings table.

## The dev overlay

```ts
createDevOverlay(ui, { loop, entities: () => enemies.size });
```

Frame time (average and worst), steps per frame and the entity count, in a corner, updated four
times a second. It does nothing unless the build is a dev build (`__KARNI_GAME_DEV__` of the
[Vite preset](game-client.md#building-for-portals)), so a build carries no overlay. `enabled: true`
shows it in a build. Screen readers skip it.

## Words

Every word the kit shows is in one table, `defaultStrings`, and `strings` replaces any of them. A
value may hold `{name}` places the kit fills (`"{value}%"`). A game in another language passes a
whole table, and no call site changes. `keyName(code, t)` names a key for people ("KeyW" is "W").

```ts
createUi({ strings: { pauseTitle: "Pause", resume: "Weiter", quit: "Beenden" } });
```

## Keyboard, screen readers, colour and small screens

- Every control is a native element (`button`, `input`, `fieldset`), so Tab order, Enter, Space
  and the arrow keys on a slider work as the browser defines them.
- Every control has a name: a visible label, or an `aria-label`. Dialogs are labelled by their
  title, switches have hints tied with `aria-describedby`, and the kit's tests run axe on every
  piece.
- Focus is visible (a 3 pixel outline), never lost behind a dialog and given back after it.
- The colours are custom properties. Light is the default, dark follows `prefers-color-scheme`,
  and `data-kg-theme` forces one. Text keeps a contrast of at least 4.5 to 1 and borders and focus
  at least 3 to 1 in both. The browser test checks it with axe.
- An error is never shown by colour alone: a toast says "!" and the boot failure screen says it
  in words.
- Panels fit a phone width (16 pixel gutters, no sideways scroll), scroll inside themselves when
  tall, and every target is at least 44 pixels.
- Reduced motion, from the system or the setting, switches off the kit's own animation.

## Escape hatches

- Replace any word, or the whole stylesheet (`styles: false`), or any colour.
- `ui.dialog` takes any element as `body`, so a game builds its own panels on the same focus rules.
- Every piece is a function that takes the layer, so a game uses the ones it needs and the rest
  are not bundled.
- Canvas-drawn buttons stay the game's own. The kit does not stop them.
