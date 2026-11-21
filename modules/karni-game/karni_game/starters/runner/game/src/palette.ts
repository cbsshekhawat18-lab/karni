// The game's colours. Everything the player must tell apart (the runner, a coin, a spike, the
// ground, a cloud to land on) differs in lightness and in shape, not only in hue, and the hues
// come from the Okabe-Ito set (@karni/game/ui's COLOUR_SAFE), which stays apart for the common
// kinds of colour blindness. The colour-safe setting goes further: outlines on everything the
// player touches, and the spikes in black and white.
import { COLOUR_SAFE } from "@karni/game/ui";

export interface Palette {
    skyTop: string;
    skyBottom: string;
    sun: string;
    farHills: string;
    nearHills: string;
    cloud: string;
    grass: string;
    grassLight: string;
    star: string;
    rock: string;
    rockShade: string;
    spike: string;
    spikeEdge: string;
    coin: string;
    coinShine: string;
    runner: string;
    runnerShade: string;
    eye: string;
    text: string;
    textEdge: string;
    /** An outline on everything the player touches, or null. */
    outline: string | null;
}

export const PALETTE: Palette = {
    skyTop: "#16324f",
    skyBottom: "#3d7ab8",
    sun: "#f6d99a",
    farHills: "#2f5f8a",
    nearHills: "#28506f",
    cloud: "#eef4fa",
    grass: COLOUR_SAFE.green,
    grassLight: "#5fd3a8",
    star: "#dfe9f5",
    rock: "#5b4a3a",
    rockShade: "#463829",
    spike: COLOUR_SAFE.vermillion,
    spikeEdge: "#fbe3d4",
    coin: COLOUR_SAFE.yellow,
    coinShine: "#fffbe0",
    runner: COLOUR_SAFE.orange,
    runnerShade: "#a36f00",
    eye: "#10202f",
    text: "#f8f9fa",
    textEdge: "#0b1d33",
    outline: null,
};

/** The colour-safe setting: outlines, and spikes that read in black and white. */
export const SAFE_PALETTE: Palette = {
    ...PALETTE,
    spike: COLOUR_SAFE.black,
    spikeEdge: "#ffffff",
    outline: "#0b1d33",
};

/** What each cosmetic looks like. */
export const COSMETICS: Record<string, { colors: readonly string[]; label: string }> = {
    "spark-trail": { colors: [COLOUR_SAFE.skyBlue, "#d8f0ff"], label: "Blue sparks behind the runner" },
    "comet-trail": { colors: [COLOUR_SAFE.purple, COLOUR_SAFE.orange], label: "A long comet tail" },
    cap: { colors: [COLOUR_SAFE.blue], label: "A blue cap" },
    crown: { colors: [COLOUR_SAFE.yellow, COLOUR_SAFE.vermillion], label: "A gold crown" },
};
