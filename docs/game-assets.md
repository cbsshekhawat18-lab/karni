---
description: "Assets in @karni/game/assets (experimental): a manifest of images, fonts, sounds and data files in named groups, loading with progress and retries, unloading to free memory, fonts before the first text, WebP copies made at build time, a size budget per group and no file from a host the build does not allow."
---

# Assets (@karni/game/assets)

!!! warning "Experimental"
    `@karni/game/assets` is [experimental](stability.md#experimental-names): a name
    or an option may change in a minor release, with a CHANGELOG entry.

A game's files are loaded in groups. A group is what one screen or one stage needs: it loads
with a progress bar before the scene that uses it, and it unloads after that scene is left, so
the memory of a stage's art is not held for the rest of the session. A small game with a few
shapes needs none of this and loads nothing.

`@karni/game/assets` has no dependency and is tree-shaken. The whole entry has a gzip budget
(tested, see [the numbers](#sizes)).

```ts
import { createAssets } from "@karni/game/assets";
```

## The folder is the manifest

With the Vite preset, the `assets/` folder of the project is the manifest. Each folder on its
first level is a group, files directly in `assets/` go in the group `core`, and a file is named
by its path inside the group without the extension:

```
assets/
  core/hero.png          core / hero
  core/stages.json       core / stages
  fonts/Inter-Bold.woff2 fonts / Inter-Bold
  meadow/bg.png          meadow / bg
  meadow/ui/button.png   meadow / ui/button
```

The kind of a file comes from its extension: images (`png jpg jpeg gif webp avif svg`), fonts
(`woff2 woff ttf otf`), sounds (`ogg mp3 wav m4a opus`) and data (`json txt csv tsv bin`). Other
files are left out. Two files that would get one name (`hero.png` and `hero.jpg`) stop the build.

```ts
// vite.config.ts
karniGame({
  assets: {
    budget: { core: 200_000, "*": 1_500_000 },   // bytes a group may download
    types: "src/karni-assets.gen.d.ts",           // exact names for the type checker
  },
});
```

```ts
import { manifest, assetHosts } from "virtual:karni-game/assets";
const assets = createAssets({ manifest, audio, allowHosts: assetHosts });
```

The `types` file is written by the build and committed. It makes `assets.image("meadow", "bg")`
a type error when the group or the file does not exist. Without it the names are plain strings.
The preset reads the folder at the start of a build or a dev server: restart the dev server after
adding a file. A project without the folder gets no manifest and no report. `assets: false` turns
the feature off.

A manifest can also be written by hand, with the names kept for the type checker:

```ts
import { defineManifest } from "@karni/game/assets";

const manifest = defineManifest({
  groups: { core: { hero: { kind: "image", url: "img/hero.png" } } },
});
```

## Loading with progress

```ts
await assets.load("core", {
  onProgress: ({ fraction, loaded, total }) => bar.set(fraction),
});
const hero = assets.image("core", "hero");   // { source, width, height }
context.drawImage(hero.source, x, y);
```

`fraction` goes from 0 to 1 and never goes back. It counts bytes when the manifest knows every
file's size (the preset writes them), and files otherwise. A second `load` of a group that is
loading shares the first, and a group that is loaded resolves at once. This is the function a
loading scene of [Scenes](game-scenes.md) calls: it shows a progress bar and moves on when the
promise resolves.

| Kind | You get | How it loads |
|---|---|---|
| image | `assets.image(group, name)`: `source` (pass it to `drawImage`), `width`, `height` | decoded with `createImageBitmap`, so the decode runs off the main thread where the browser allows. Without it, an `<img>` and `decode()` |
| font | the font is added to the page | added with `FontFace` before the load resolves, so the first text draws in it |
| sound | `assets.sound(group, name)`: an `AudioBuffer` | decoded on the audio layer's context (give `audio`) |
| data | `assets.data(group, name)` | `.json` parsed, `.txt` and `.csv` as text, anything else as an `ArrayBuffer`. Typed `unknown`: check it before use |

`await assets.fontsReady()` resolves once every font of the loads in flight is usable. Asking for
a file of a group that is not loaded, or a name that is not in it, throws an error that names what
there is.

## A failure a player can read

Each file is tried again after a failure: two more tries by default, waiting 250 ms, then 500 ms
(`retries` and `retryDelay` change that), and a try ends after 20 seconds (`timeout`). When a file
still fails, `load` rejects with an `AssetLoadError` whose message names the files and the reason:

```
Could not load 2 files of "meadow": bg (HTTP 404), clouds (timed out)
```

Run the load inside `guardBoot` of [Game UI](game-ui.md) and a player sees the boot failure screen
with the message under Details and a Try again button, which loads again:

```ts
void guardBoot(async () => {
  await assets.load("core", { onProgress });
  show("title");
});
```

A game that can do without some files passes `strict: false`: `load` then resolves with
`{ loaded, failed }` and the game goes on. `signal` cancels a load, and the files that had loaded
are freed.

## Unloading

```ts
const freed = assets.unload("meadow");   // bytes of memory freed
assets.memory("cave");                   // an estimate for a loaded group, in bytes
```

`unload` closes each bitmap (the pixels are freed, not left for the garbage collector), removes
the group's fonts, and drops the buffers and data. Unload the last stage's group after the
transition into the next scene, and load the next stage's group before it. The memory figure is
width times height times four for an image, frames times channels times four for a sound, and
the size of a data file. It is an estimate for the dev overlay and for tests, not a measurement.

## WebP copies

In a build, the preset writes a WebP copy of each PNG and JPEG that is smaller than the original,
and lists both. A browser that decodes WebP downloads the copy, and the original is the fallback:
one try on the copy, then the original with its retries. The sizes in the manifest and the budget
are what the player downloads, so the copy counts.

The encoder is the `sharp` package, which the project installs itself (`npm i -D sharp`). It is
not a dependency of `@karni/game`. Without it the build says so and keeps the originals. Pass
another encoder with `assets.webp.encode` (bytes in, WebP bytes out), and `webp: false` keeps the
originals. Copies are cached in `node_modules/.cache/karni-game/webp` by the content of the file,
so a second build does not encode again. A copy that is not smaller is dropped.

## A size budget for each group

`budget` is a number for every group, or a table by group with `"*"` for the rest. The default is
2 MiB. The build writes `karni-assets.json` into the package, and `checkPackage` (the check of
`karni-game package` and `karni-game check`) fails a group over its budget:

```
FAIL web: 1 problem(s)
  asset-budget karni-assets.json: the asset group "cave" is 2310000 bytes (14 files), over its budget of 2097152: split it into groups that load when needed, or shrink the files
```

The budget is per group because a group is what one load downloads. The portal's whole-package
budget still applies on top.

## Hosts

A file is fetched from the page's own origin, a `data:` URL or a `blob:` URL, or from a host in
`allowHosts`. Any other host is refused with a readable reason, and nothing is fetched. The preset's
`assetHosts` is the hosts the build allows: the portal's, the game API's and any named in
`assets.hosts`. The package check also finds a host written into the built files, as it does for
every other file.

## Escape hatches

- `platform` replaces any browser piece the loader uses: `fetch`, `decodeImage`, `addFont`,
  `removeFont`, `webp` and `wait`. An engine that decodes its own textures passes its own.
- `assets: false`, `webp: false` and a hand-written manifest let a project use none of the preset.
- `retries`, `retryDelay`, `timeout` and `concurrency` (6 files at once) are options.
- A game that needs no groups can skip the entry: the loop, the audio layer and `fetch` are enough.

## What a drawing layer needs

The images are plain `ImageBitmap` or `HTMLImageElement` values in `source`, with `width` and
`height`. A sprite or tilemap code takes `source` for `drawImage`. `assets.unload` closes the
bitmaps, so a sprite must not draw from a group it has unloaded: `assets.isLoaded(group)` says
whether it may.

## Sizes

The gzip size of the whole entry is checked by a test against a budget of 3400 bytes.
A game that loads one group and nothing else bundles about 3000 bytes.
