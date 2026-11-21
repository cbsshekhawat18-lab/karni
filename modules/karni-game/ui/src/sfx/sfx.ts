import type { GameAudio, Sound } from "../audio";
import { renderSpec, type SoundSpec } from "./synth";

export interface SfxOptions {
  audio: Pick<GameAudio, "context" | "unlocked" | "play" | "onUnlock">;
  /** Sounds playing at once, over every name. At the limit the oldest is stopped. Default 16. */
  voices?: number;
  /** A number in [0, 1) for the pitch and volume variation. Default `Math.random`. */
  random?: () => number;
}

export interface SfxPlayOptions {
  /** 0 to 1 on top of the sound's own volume. Default 1. */
  volume?: number;
  /** Playback rate, 1 is as made. Default 1. */
  rate?: number;
  /** Random pitch change: 0.1 plays between 0.9 and 1.1 times the rate. Default 0. */
  pitchVariation?: number;
  /** Random volume change: 0.2 plays between 0.8 and 1 times the volume. Default 0. */
  volumeVariation?: number;
  /** Most of this name playing at once. Over it the oldest of the name stops. Default 4. */
  voices?: number;
  /** Lower the music while this plays (true uses the defaults). */
  duck?: boolean | DuckOptions;
}

export interface DuckOptions {
  /** The music's level while ducked, 0 to 1. Default 0.3. */
  to?: number;
  /** Seconds to go down. Default 0.05. */
  attack?: number;
  /** Seconds to stay down. Default 0.4. */
  hold?: number;
  /** Seconds to come back. Default 0.5. */
  release?: number;
}

export interface MusicOptions {
  /** Seconds to fade in, and to fade the last track out. Default 1. */
  fade?: number;
  /** 0 to 1. Default 1. */
  volume?: number;
}

export interface Sfx {
  /** Name a sound: a spec (made into samples on first play) or a decoded buffer. */
  define(name: string, sound: SoundSpec | AudioBuffer): void;
  has(name: string): boolean;
  /** Play a named sound. Null (silently) before the first gesture, for an unknown name, or when it cannot play. */
  play(name: string, options?: SfxPlayOptions): Sound | null;
  /** Loop a named sound as the music, crossfading from the last track. Asked before the first gesture it starts then. */
  music(name: string, options?: MusicOptions): void;
  stopMusic(options?: { fade?: number }): void;
  /** Lower the music for a while (a stinger, a line of speech). Runs on the audio clock, so a pause holds it. */
  duck(options?: DuckOptions): void;
  /** Stop every sound and the music. */
  stopAll(): void;
  /** Sounds playing now. */
  readonly voices: number;
}

interface Track {
  sound: Sound;
  level: number;
}

const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/**
 * Sounds on the audio layer's buses, so its volumes, mutes and pause apply
 * as they do to everything else: one-shots with pitch and volume variation
 * and a voice limit, music with crossfade and ducking, and procedural sounds
 * from `tone`, `sweep`, `noise` and `arpeggio`.
 */
export function createSfx(options: SfxOptions): Sfx {
  const { audio } = options;
  const random = options.random ?? Math.random;
  const limit = Math.max(1, options.voices ?? 16);
  const defs = new Map<string, SoundSpec | AudioBuffer>();
  const buffers = new Map<string, AudioBuffer>();
  const playing: { name: string; sound: Sound }[] = [];
  let tracks: Track[] = [];
  let wanted: { name: string; options: MusicOptions } | null = null;
  let duckTo = 1;
  let duckEnds = -1;

  const bufferOf = (name: string): AudioBuffer | null => {
    const cached = buffers.get(name);
    if (cached) return cached;
    const def = defs.get(name);
    const ctx = audio.context;
    if (!def || !ctx) return null;
    if (!("kind" in def)) {
      buffers.set(name, def);
      return def;
    }
    const samples = renderSpec(def, ctx.sampleRate);
    const buffer = ctx.createBuffer(1, samples.length, ctx.sampleRate);
    buffer.getChannelData(0).set(samples);
    buffers.set(name, buffer);
    return buffer;
  };

  const prune = (): void => {
    for (let i = playing.length - 1; i >= 0; i -= 1) {
      if (!playing[i]?.sound.playing) playing.splice(i, 1);
    }
  };

  const level = (track: Track, at: number): number =>
    at < duckEnds ? track.level * duckTo : track.level;

  const startDuck = (settings: DuckOptions): void => {
    const ctx = audio.context;
    if (!ctx) return;
    const to = settings.to ?? 0.3;
    const attack = settings.attack ?? 0.05;
    const hold = settings.hold ?? 0.4;
    const release = settings.release ?? 0.5;
    const now = ctx.currentTime;
    // A duck inside another one goes as low as the lower of the two.
    duckTo = now < duckEnds ? Math.min(duckTo, to) : to;
    duckEnds = Math.max(duckEnds, now + attack + hold);
    for (const track of tracks) {
      const param = track.sound.gain.gain;
      const from = param.value;
      param.cancelScheduledValues(now);
      param.setValueAtTime(from, now);
      param.linearRampToValueAtTime(track.level * duckTo, now + attack);
      param.setValueAtTime(track.level * duckTo, duckEnds);
      param.linearRampToValueAtTime(track.level, duckEnds + release);
    }
  };

  const fadeOut = (track: Track, seconds: number): void => {
    const ctx = audio.context;
    const param = track.sound.gain.gain;
    if (!ctx || seconds <= 0) {
      track.sound.stop();
      return;
    }
    const now = ctx.currentTime;
    const from = param.value;
    param.cancelScheduledValues(now);
    param.setValueAtTime(from, now);
    param.linearRampToValueAtTime(0, now + seconds);
    // The source stops itself once it is silent. It follows the audio clock, so a pause holds it.
    const stopAt = now + seconds;
    const watch = (): void => {
      if (!track.sound.playing) return;
      if ((audio.context?.currentTime ?? stopAt) >= stopAt) track.sound.stop();
      else setTimeout(watch, 100);
    };
    setTimeout(watch, Math.max(50, seconds * 1000));
  };

  const startMusic = (name: string, settings: MusicOptions): void => {
    const buffer = bufferOf(name);
    const ctx = audio.context;
    if (!buffer || !ctx) return;
    const fade = settings.fade ?? 1;
    const target = Math.min(1, Math.max(0, settings.volume ?? 1));
    const sound = audio.play(buffer, { loop: true, bus: "music", volume: fade > 0 ? 0 : target });
    if (!sound) return;
    const track: Track = { sound, level: target };
    for (const old of tracks) fadeOut(old, fade);
    tracks = [track];
    if (fade > 0) {
      const now = ctx.currentTime;
      const param = sound.gain.gain;
      param.setValueAtTime(0, now);
      param.linearRampToValueAtTime(level(track, now + fade), now + fade);
    }
  };

  audio.onUnlock(() => {
    if (wanted) {
      const { name, options: settings } = wanted;
      wanted = null;
      startMusic(name, settings);
    }
  });

  return {
    define(name, sound) {
      defs.set(name, sound);
      buffers.delete(name);
    },
    has: (name) => defs.has(name),
    play(name, play = {}) {
      if (!audio.unlocked) return null;
      const buffer = bufferOf(name);
      if (!buffer) return null;
      prune();
      const own = playing.filter((entry) => entry.name === name);
      const perName = Math.max(1, play.voices ?? 4);
      while (own.length >= perName) own.shift()?.sound.stop();
      prune();
      while (playing.length >= limit) playing.shift()?.sound.stop();
      const pitch = play.pitchVariation ?? 0;
      const loud = play.volumeVariation ?? 0;
      const rate = (play.rate ?? 1) * lerp(1 - pitch, 1 + pitch, random());
      const volume = (play.volume ?? 1) * lerp(1 - loud, 1, random());
      const sound = audio.play(buffer, { rate, volume });
      if (!sound) return null;
      playing.push({ name, sound });
      if (play.duck) startDuck(play.duck === true ? {} : { hold: buffer.duration, ...play.duck });
      return sound;
    },
    music(name, music = {}) {
      if (!defs.has(name)) return;
      if (!audio.unlocked) {
        wanted = { name, options: music };
        return;
      }
      wanted = null;
      startMusic(name, music);
    },
    stopMusic(stop = {}) {
      wanted = null;
      for (const track of tracks) fadeOut(track, stop.fade ?? 0.5);
      tracks = [];
    },
    duck(settings = {}) {
      startDuck(settings);
    },
    stopAll() {
      wanted = null;
      for (const { sound } of playing) sound.stop();
      playing.length = 0;
      for (const track of tracks) track.sound.stop();
      tracks = [];
    },
    get voices() {
      prune();
      return playing.length;
    },
  };
}
