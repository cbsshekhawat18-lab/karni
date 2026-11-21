/**
 * Procedural sound as plain data. A spec is rendered to samples by pure
 * functions, so it is tested without audio and a game ships no sound files.
 */

/** Seconds: attack up, decay to `sustain` (a level from 0 to 1), hold, release at the end. */
export interface Envelope {
  attack?: number;
  decay?: number;
  sustain?: number;
  release?: number;
}

export type Wave = "sine" | "square" | "saw" | "triangle";

export interface ToneSpec {
  kind: "tone";
  wave: Wave;
  /** Hertz at the start. */
  freq: number;
  /** Hertz at the end: the pitch slides there (exponentially). Default `freq`. */
  freqEnd?: number;
  /** Seconds. */
  duration: number;
  /** 0 to 1. Default 0.5. */
  volume?: number;
  envelope?: Envelope;
  /** Square wave: the share of each cycle that is high. Default 0.5. */
  duty?: number;
}

export interface NoiseSpec {
  kind: "noise";
  duration: number;
  volume?: number;
  envelope?: Envelope;
  /** A low-pass at this many Hertz (a duller noise). Default none. */
  lowpass?: number;
  /** Where the low-pass ends, for a noise that darkens or brightens. Default `lowpass`. */
  lowpassEnd?: number;
}

/** Specs one after another: `step` seconds from the start of one to the start of the next. */
export interface SequenceSpec {
  kind: "sequence";
  steps: readonly SoundSpec[];
  step: number;
}

/** Specs at the same time. */
export interface MixSpec {
  kind: "mix";
  layers: readonly SoundSpec[];
}

export type SoundSpec = ToneSpec | NoiseSpec | SequenceSpec | MixSpec;

const DEFAULT_ENVELOPE: Required<Envelope> = {
  attack: 0.004,
  decay: 0.04,
  sustain: 0.7,
  release: 0.04,
};

/** The envelope's level (0 to 1) `t` seconds into a sound that lasts `duration`. */
export function envelopeAt(t: number, duration: number, envelope: Envelope = {}): number {
  if (t < 0 || t >= duration) return 0;
  const e = { ...DEFAULT_ENVELOPE, ...envelope };
  // The parts never run past the sound: shrink them in proportion when they do not fit.
  const total = e.attack + e.decay + e.release;
  const scale = total > duration ? duration / total : 1;
  const attack = e.attack * scale;
  const decay = e.decay * scale;
  const release = e.release * scale;
  if (t < attack) return attack === 0 ? 1 : t / attack;
  if (t < attack + decay) return 1 - (1 - e.sustain) * ((t - attack) / decay);
  const releaseAt = duration - release;
  if (t < releaseAt) return e.sustain;
  return release === 0 ? 0 : e.sustain * (1 - (t - releaseAt) / release);
}

/** One cycle position `phase` (0 to 1) of a wave, from -1 to 1. */
export function waveAt(wave: Wave, phase: number, duty = 0.5): number {
  const p = phase - Math.floor(phase);
  switch (wave) {
    case "sine":
      return Math.sin(p * Math.PI * 2);
    case "square":
      return p < duty ? 1 : -1;
    case "saw":
      return p * 2 - 1;
    case "triangle":
      return p < 0.5 ? p * 4 - 1 : 3 - p * 4;
  }
}

/** A small seeded generator in [0, 1), so a noise burst renders the same every time. */
export function noiseSource(seed = 0x9e3779b9): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state ^= state << 13;
    state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5;
    state >>>= 0;
    return state / 4294967296;
  };
}

/** How many seconds a spec lasts. */
export function lengthOf(spec: SoundSpec): number {
  if (spec.kind === "sequence") {
    const last = spec.steps[spec.steps.length - 1];
    return last ? spec.step * (spec.steps.length - 1) + lengthOf(last) : 0;
  }
  if (spec.kind === "mix") return Math.max(0, ...spec.layers.map(lengthOf));
  return spec.duration;
}

function add(into: Float32Array, from: Float32Array, offset: number): void {
  for (let i = 0; i < from.length && offset + i < into.length; i += 1) {
    into[offset + i] = (into[offset + i] ?? 0) + (from[i] ?? 0);
  }
}

/**
 * Render a spec to mono samples at `sampleRate`. The sum is clipped to
 * [-1, 1] so layers cannot go past full scale.
 */
export function renderSpec(
  spec: SoundSpec,
  sampleRate: number,
  random: () => number = noiseSource(),
): Float32Array {
  const length = Math.max(1, Math.round(lengthOf(spec) * sampleRate));
  const out = new Float32Array(length);
  if (spec.kind === "sequence") {
    spec.steps.forEach((step, index) => {
      add(out, renderSpec(step, sampleRate, random), Math.round(index * spec.step * sampleRate));
    });
  } else if (spec.kind === "mix") {
    for (const layer of spec.layers) add(out, renderSpec(layer, sampleRate, random), 0);
  } else if (spec.kind === "tone") {
    const volume = spec.volume ?? 0.5;
    const end = spec.freqEnd ?? spec.freq;
    let phase = 0;
    for (let i = 0; i < length; i += 1) {
      const t = i / sampleRate;
      // An exponential slide, as pitch is heard, whatever the two ends are.
      const freq = spec.freq * Math.pow(end / spec.freq, Math.min(1, t / spec.duration));
      out[i] =
        waveAt(spec.wave, phase, spec.duty) * volume * envelopeAt(t, spec.duration, spec.envelope);
      phase += freq / sampleRate;
    }
  } else {
    const volume = spec.volume ?? 0.5;
    const from = spec.lowpass;
    const to = spec.lowpassEnd ?? from;
    let last = 0;
    for (let i = 0; i < length; i += 1) {
      const t = i / sampleRate;
      let sample = random() * 2 - 1;
      if (from !== undefined && to !== undefined) {
        const cutoff = from + (to - from) * Math.min(1, t / spec.duration);
        const a = 1 - Math.exp((-2 * Math.PI * cutoff) / sampleRate);
        last += a * (sample - last);
        sample = last;
      }
      out[i] = sample * volume * envelopeAt(t, spec.duration, spec.envelope);
    }
  }
  for (let i = 0; i < out.length; i += 1) out[i] = Math.max(-1, Math.min(1, out[i] ?? 0));
  return out;
}

type ToneOptions = Partial<Omit<ToneSpec, "kind" | "freq" | "duration" | "freqEnd" | "wave">> & {
  wave?: Wave;
};

/** A steady note. */
export const tone = (freq: number, duration: number, options: ToneOptions = {}): ToneSpec => ({
  kind: "tone",
  wave: "square",
  freq,
  duration,
  ...options,
});

/** A note that slides from one pitch to another. */
export const sweep = (
  from: number,
  to: number,
  duration: number,
  options: ToneOptions = {},
): ToneSpec => ({ kind: "tone", wave: "square", freq: from, freqEnd: to, duration, ...options });

/** A burst of noise. */
export const noise = (
  duration: number,
  options: Partial<Omit<NoiseSpec, "kind" | "duration">> = {},
): NoiseSpec => ({ kind: "noise", duration, ...options });

/** Notes in turn, `step` seconds apart. */
export const arpeggio = (
  freqs: readonly number[],
  step: number,
  options: ToneOptions & { duration?: number } = {},
): SequenceSpec => ({
  kind: "sequence",
  step,
  steps: freqs.map((freq) => tone(freq, options.duration ?? step * 1.5, options)),
});

/** Sounds at once. */
export const mix = (...layers: SoundSpec[]): MixSpec => ({ kind: "mix", layers });

/** A few sounds nearly every game wants, as specs to use as they are or to start from. */
export const presets = {
  blip: (freq = 660): SoundSpec => tone(freq, 0.08, { wave: "square", volume: 0.3 }),
  click: (): SoundSpec => tone(1200, 0.03, { wave: "triangle", volume: 0.3 }),
  jump: (): SoundSpec => sweep(280, 640, 0.14, { wave: "square", volume: 0.3 }),
  coin: (): SoundSpec =>
    arpeggio([988, 1319], 0.07, { wave: "square", volume: 0.3, duration: 0.14 }),
  powerup: (): SoundSpec =>
    arpeggio([392, 523, 659, 784], 0.06, { wave: "triangle", volume: 0.4, duration: 0.1 }),
  hit: (): SoundSpec =>
    mix(
      noise(0.12, { volume: 0.5, lowpass: 3000, lowpassEnd: 600 }),
      sweep(220, 70, 0.12, { wave: "square", volume: 0.3 }),
    ),
  explosion: (): SoundSpec =>
    mix(
      noise(0.6, { volume: 0.6, lowpass: 2500, lowpassEnd: 150, envelope: { release: 0.4 } }),
      sweep(120, 40, 0.5, { wave: "saw", volume: 0.3 }),
    ),
  lose: (): SoundSpec => arpeggio([392, 330, 262, 196], 0.12, { wave: "triangle", volume: 0.4 }),
} as const;
