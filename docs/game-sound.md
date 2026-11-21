---
description: "Sound in @karni/game/sfx (experimental): one-shots with pitch and volume variation and a voice limit, music with crossfade and ducking, and procedural tones, sweeps and noise with envelopes, on the audio layer's buses, mutes and pause, silent until the first gesture."
---

# Sound (@karni/game/sfx)

!!! warning "Experimental"
    `@karni/game/sfx` is [experimental](stability.md#experimental-names): a name
    or an option may change in a minor release, with a CHANGELOG entry.

Most small games make their own sounds: a blip, a sweep, a burst of noise, each with an envelope.
`@karni/game/sfx` makes them from a few numbers, so a game ships no sound file, and plays them
on the buses of the [audio layer](game-client.md) (`master`, `music`, `effects`). Its volumes, its
mutes by source (player, ad, portal) and its pause apply to every sound here as they do to
everything else, with no code of the game's.

It has no dependency and is tree-shaken. The whole entry has a gzip budget (tested, see
[the numbers](#sizes)).

```ts
import { createAudio } from "@karni/game";
import { arpeggio, createSfx, presets } from "@karni/game/sfx";

const audio = createAudio();
audio.unlockOn(input);              // the first tap or key starts audio
const sfx = createSfx({ audio });

sfx.define("jump", presets.jump());
sfx.define("theme", arpeggio([262, 330, 392, 330], 0.3, { wave: "triangle", volume: 0.2 }));

sfx.play("jump", { pitchVariation: 0.06, volumeVariation: 0.2 });
sfx.music("theme", { fade: 1.2 });
```

## Silent until the first gesture

A browser does not let a page make sound before the player has tapped or pressed a key. Until
then `play` returns `null` and does nothing, and `music` remembers the track and starts it on
the first gesture (the audio layer's `onUnlock`). When the game is paused, the audio context is
suspended: nothing plays, and ducks and fades, which run on the audio clock, hold where they are.
A sound asked for while paused returns `null`.

## One-shots

```ts
sfx.play("coin", { volume: 0.8, rate: 1, pitchVariation: 0.05, volumeVariation: 0.2, voices: 3 });
```

| Option | Does |
|---|---|
| `volume` | 0 to 1 on top of the sound's own volume. |
| `rate` | Playback rate, so pitch. 1 is as made. |
| `pitchVariation` | `0.1` plays at a random rate between 0.9 and 1.1 times `rate`, so a repeated sound does not repeat exactly. |
| `volumeVariation` | `0.2` plays between 0.8 and 1 times the volume. |
| `voices` | The most of this name at once, default 4. Over it the oldest of the name stops. |
| `duck` | Lower the music while it plays: `true`, or `{ to, attack, hold, release }`. |

`createSfx({ voices })` is the limit over every name, default 16: past it the oldest sound stops,
so a burst of events cannot pile up. `sfx.voices` is the number playing. `random` replaces
`Math.random` for the variation, which a test does to get exact numbers.

## Music, crossfade and ducking

```ts
sfx.music("calm", { fade: 2, volume: 0.8 });   // fades in over two seconds
sfx.music("fight", { fade: 2 });               // crossfades: calm fades out as fight fades in
sfx.duck({ to: 0.3, attack: 0.05, hold: 0.4, release: 0.5 });
sfx.stopMusic({ fade: 1 });
```

Music loops. A new track fades the last one out over the same `fade` and stops it once it is
silent. `duck` lowers the music to `to` (a share of its level), holds, and brings it back. A duck
inside another goes as low as the lower of the two. The ramps are scheduled on the audio clock,
so they are exact and a pause holds them.

## Procedural sounds

A sound is a spec, plain data, rendered to samples the first time it plays and then kept.

```ts
import { arpeggio, mix, noise, sweep, tone } from "@karni/game/sfx";

tone(440, 0.2, { wave: "square", volume: 0.3 });                       // a steady note
sweep(280, 640, 0.14, { wave: "square" });                             // a slide in pitch
noise(0.3, { lowpass: 3000, lowpassEnd: 400, envelope: { release: 0.2 } });   // a burst that darkens
arpeggio([988, 1319], 0.07, { duration: 0.14 });                       // notes in turn
mix(noise(0.12, { lowpass: 3000 }), sweep(220, 70, 0.12));             // layers at once
```

- Waves are `sine`, `square` (with `duty`), `saw` and `triangle`.
- A pitch slide is exponential, as pitch is heard, whatever the two ends are.
- An envelope is `{ attack, decay, sustain, release }` in seconds, with sustain a level from 0
  to 1. The parts shrink to fit a short sound.
- Noise is made by a small seeded generator, so a burst renders the same every time.
- A mix is clipped to full scale.

`presets` has `blip`, `click`, `jump`, `coin`, `powerup`, `hit`, `explosion` and `lose`, to use as
they are or to start from. `renderSpec(spec, sampleRate)` is a pure function from a spec to a
`Float32Array`, which a test can inspect and an editor can draw.

A sound from a file works the same way: `sfx.define("boom", assets.sound("stage1", "boom"))` takes
the decoded buffer that [Assets](game-assets.md) loads.

## Escape hatches

- `createSfx({ audio })` takes any object with `context`, `unlocked`, `play` and `onUnlock`, so a
  game with its own audio can use the synth and the variation with its own player.
- `renderSpec` and the spec helpers work with no audio at all.
- `audio.bus("music")` and `audio.bus("effects")` are the gain nodes of the buses, to connect a
  game's own graph beside the sfx.

## Sizes

The gzip size of the whole entry is checked by a test against a budget of 3100 bytes. A game
that only renders a tone bundles about 1100 bytes.
