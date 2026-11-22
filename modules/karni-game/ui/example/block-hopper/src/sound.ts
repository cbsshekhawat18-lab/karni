import type { GameAudio } from "@karni/game";
import { arpeggio, createSfx, presets, type Sfx } from "@karni/game/sfx";

/**
 * Block Hopper ships no sound file: every sound is a few numbers that the
 * sfx module renders on first play, and the two themes are arpeggios that loop.
 */
export function createSounds(audio: GameAudio): Sfx {
  const sfx = createSfx({ audio, voices: 8 });
  sfx.define("jump", presets.jump());
  sfx.define("land", presets.click());
  sfx.define("coin", presets.coin());
  sfx.define("fall", presets.lose());
  sfx.define(
    "theme-meadow",
    arpeggio([262, 330, 392, 330, 294, 349, 440, 349], 0.3, {
      wave: "triangle",
      volume: 0.16,
      duration: 0.4,
    }),
  );
  sfx.define(
    "theme-cave",
    arpeggio([196, 233, 294, 233, 175, 208, 262, 208], 0.34, {
      wave: "sine",
      volume: 0.22,
      duration: 0.5,
    }),
  );
  return sfx;
}

/** What each rule event sounds like. The coin and the jump vary a little, so a run does not repeat itself. */
export function playEvent(sfx: Sfx, event: string): void {
  if (event === "jump") sfx.play("jump", { pitchVariation: 0.06, volumeVariation: 0.2 });
  else if (event === "land") sfx.play("land", { volume: 0.5, pitchVariation: 0.1, voices: 2 });
  else if (event === "coin") sfx.play("coin", { pitchVariation: 0.04 });
  else if (event === "fall") sfx.play("fall", { duck: true });
}
