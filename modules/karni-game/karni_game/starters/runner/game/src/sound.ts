// Every sound of the game is made by @karni/game/sfx from a few numbers: no audio files.
import type { GameAudio } from "@karni/game";
import { arpeggio, createSfx, mix, presets, sweep, tone, type Sfx } from "@karni/game/sfx";
import type { RunEvent } from "./rules";

export function createSounds(audio: GameAudio): Sfx {
    const sfx = createSfx({ audio, voices: 10 });
    sfx.define("jump", presets.jump());
    sfx.define("double", sweep(420, 900, 0.12, { wave: "square", volume: 0.25 }));
    sfx.define("land", presets.click());
    sfx.define("coin", presets.coin());
    sfx.define("spike", presets.hit());
    sfx.define("fall", presets.lose());
    sfx.define("revive", presets.powerup());
    sfx.define("buy", mix(tone(784, 0.08, { wave: "triangle", volume: 0.3 }), tone(1175, 0.16, { wave: "triangle", volume: 0.25 })));
    sfx.define(
        "music",
        arpeggio([262, 330, 392, 494, 440, 392, 330, 294, 262, 330, 392, 523, 494, 392, 330, 247], 0.18, {
            wave: "triangle",
            volume: 0.12,
            duration: 0.26,
        }),
    );
    return sfx;
}

/** What each rule event sounds like. Jumps and coins vary a little, so a run never drones. */
export function playEvent(sfx: Sfx, event: RunEvent): void {
    if (event === "jump") sfx.play("jump", { pitchVariation: 0.05, volumeVariation: 0.15 });
    else if (event === "double") sfx.play("double", { pitchVariation: 0.05 });
    else if (event === "land") sfx.play("land", { volume: 0.4, pitchVariation: 0.1, voices: 2 });
    else if (event === "coin") sfx.play("coin", { pitchVariation: 0.04 });
    else if (event === "spike") sfx.play("spike", { duck: true });
    else if (event === "fall") sfx.play("fall", { duck: true });
    else if (event === "revive") sfx.play("revive");
}
