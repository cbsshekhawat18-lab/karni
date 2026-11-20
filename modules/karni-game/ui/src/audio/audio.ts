/** The three volume controls a game's settings screen offers. */
export type Bus = "master" | "music" | "effects";

/**
 * Who muted the game. Each is kept apart, so an ad ending never unmutes a
 * player who muted, and the portal's setting never changes the player's.
 */
export type MuteSource = "player" | "ad" | "portal";

export interface AudioOptions {
  /** Starting volumes from 0 to 1. Default 1 each. */
  volumes?: Partial<Record<Bus, number>>;
  /** Make the AudioContext. Default the browser's (`AudioContext`, or the prefixed one). */
  createContext?: () => AudioContext;
  /** The fetch used by `load`. Default the global `fetch`. */
  fetch?: (url: string) => Promise<Response>;
}

export interface PlayOptions {
  /** Default "effects" (`music` uses "music"). */
  bus?: Exclude<Bus, "master">;
  /** 0 to 1, on top of the bus volume. Default 1. */
  volume?: number;
  loop?: boolean;
  /** Playback rate (pitch). Default 1. */
  rate?: number;
}

export interface Sound {
  stop(): void;
  readonly playing: boolean;
}

export interface GameAudio {
  /** The AudioContext, made on `unlock` (null before, and where Web Audio is missing). */
  readonly context: AudioContext | null;
  /** The context runs: sounds are heard. */
  readonly unlocked: boolean;
  /** Start audio. Call it from a tap or key (the input's first-gesture hook does). */
  unlock(): Promise<boolean>;
  /** Unlock on the first gesture `input` sees. */
  unlockOn(input: { onFirstGesture(callback: () => void): unknown }): void;
  volume(bus: Bus): number;
  setVolume(bus: Bus, value: number): void;
  /** Muted by any source, or by the one named. */
  isMuted(source?: MuteSource): boolean;
  setMuted(source: MuteSource, muted: boolean): void;
  readonly muted: boolean;
  /** Suspend audio for a reason ("hidden", "ad", "game"). It runs again once every reason is resumed. */
  pause(reason?: string): void;
  resume(reason?: string): void;
  readonly paused: boolean;
  /** Pause with a loop: audio pauses and resumes when the loop does. */
  follow(loop: { on(event: "pause" | "resume", listener: () => void): () => void }): () => void;
  /** A bus's gain node, to connect a game's own audio graph. Null before unlock. */
  bus(name: Bus): GainNode | null;
  /** Fetch and decode a sound. Resolves null (never rejects) when it cannot. */
  load(url: string): Promise<AudioBuffer | null>;
  /** Play a decoded sound. Returns null (silently) before unlock or without a buffer. */
  play(buffer: AudioBuffer | null, options?: PlayOptions): Sound | null;
  /** Play one music track on loop, replacing the last. Asked before unlock, it starts on unlock. */
  music(buffer: AudioBuffer | null, options?: Omit<PlayOptions, "bus">): void;
  stopMusic(): void;
  stopAll(): void;
}

const clamp = (value: number): number =>
  Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1;

function browserContext(): AudioContext {
  const scope = globalThis as unknown as {
    AudioContext?: new () => AudioContext;
    webkitAudioContext?: new () => AudioContext;
  };
  const Context = scope.AudioContext ?? scope.webkitAudioContext;
  if (!Context) throw new Error("Web Audio is not available");
  return new Context();
}

/**
 * Game audio on Web Audio: unlocked on the first gesture, master, music and
 * effects volumes, mutes kept apart by source, and a pause that follows the
 * game. Every call is safe before unlock and where Web Audio is missing.
 */
export function createAudio(options: AudioOptions = {}): GameAudio {
  const volumes: Record<Bus, number> = {
    master: clamp(options.volumes?.master ?? 1),
    music: clamp(options.volumes?.music ?? 1),
    effects: clamp(options.volumes?.effects ?? 1),
  };
  const mutes = new Set<MuteSource>();
  const pauses = new Set<string>();
  const sounds = new Set<{ source: AudioBufferSourceNode; sound: Sound }>();
  const fetcher = options.fetch ?? ((url: string) => fetch(url));
  let context: AudioContext | null = null;
  let buses: Record<Bus, GainNode> | null = null;
  let failed = false;
  let musicSound: Sound | null = null;
  let pendingMusic: { buffer: AudioBuffer; options: Omit<PlayOptions, "bus"> } | null = null;

  const apply = (): void => {
    if (!context || !buses) return;
    const at = context.currentTime;
    const set = (node: GainNode, value: number): void => {
      // A short ramp avoids a click when muting.
      node.gain.cancelScheduledValues(at);
      node.gain.setTargetAtTime(value, at, 0.01);
    };
    set(buses.master, mutes.size > 0 ? 0 : volumes.master);
    set(buses.music, volumes.music);
    set(buses.effects, volumes.effects);
  };

  const ensure = (): AudioContext | null => {
    if (context || failed) return context;
    try {
      context = (options.createContext ?? browserContext)();
      const master = context.createGain();
      master.connect(context.destination);
      const music = context.createGain();
      music.connect(master);
      const effects = context.createGain();
      effects.connect(master);
      buses = { master, music, effects };
      apply();
    } catch {
      failed = true;
      context = null;
    }
    return context;
  };

  const running = (): boolean => context?.state === "running";

  const syncPause = async (): Promise<void> => {
    if (!context) return;
    try {
      if (pauses.size > 0 && context.state === "running") await context.suspend();
      else if (pauses.size === 0 && context.state === "suspended") await context.resume();
    } catch {
      // A browser refusing to resume outside a gesture is retried on the next unlock.
    }
  };

  const play = (buffer: AudioBuffer | null, playOptions: PlayOptions = {}): Sound | null => {
    if (!buffer || !context || !buses || !running()) return null;
    try {
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.loop = playOptions.loop ?? false;
      source.playbackRate.value = playOptions.rate ?? 1;
      const gain = context.createGain();
      gain.gain.value = clamp(playOptions.volume ?? 1);
      source.connect(gain);
      gain.connect(buses[playOptions.bus ?? "effects"]);
      let playing = true;
      const entry = {
        source,
        sound: {
          stop() {
            if (!playing) return;
            playing = false;
            try {
              source.stop();
            } catch {
              // Already stopped.
            }
          },
          get playing() {
            return playing;
          },
        },
      };
      source.onended = () => {
        playing = false;
        sounds.delete(entry);
      };
      sounds.add(entry);
      source.start();
      return entry.sound;
    } catch {
      return null;
    }
  };

  const audio: GameAudio = {
    get context() {
      return context;
    },
    get unlocked() {
      return running();
    },
    async unlock() {
      const ctx = ensure();
      if (!ctx) return false;
      try {
        if (pauses.size === 0 && ctx.state !== "running") await ctx.resume();
        // Older mobile browsers start only after a sound inside the gesture.
        const silent = ctx.createBuffer(1, 1, 22050);
        const source = ctx.createBufferSource();
        source.buffer = silent;
        source.connect(ctx.destination);
        source.start();
      } catch {
        return false;
      }
      if (pendingMusic && running()) {
        const { buffer, options: musicOptions } = pendingMusic;
        pendingMusic = null;
        audio.music(buffer, musicOptions);
      }
      return running();
    },
    unlockOn(input) {
      input.onFirstGesture(() => {
        void audio.unlock();
      });
    },
    volume: (bus) => volumes[bus],
    setVolume(bus, value) {
      volumes[bus] = clamp(value);
      apply();
    },
    isMuted: (source) => (source ? mutes.has(source) : mutes.size > 0),
    setMuted(source, muted) {
      if (muted) mutes.add(source);
      else mutes.delete(source);
      apply();
    },
    get muted() {
      return mutes.size > 0;
    },
    pause(reason = "game") {
      pauses.add(reason);
      void syncPause();
    },
    resume(reason = "game") {
      pauses.delete(reason);
      void syncPause();
    },
    get paused() {
      return pauses.size > 0;
    },
    follow(loop) {
      const offPause = loop.on("pause", () => audio.pause("loop"));
      const offResume = loop.on("resume", () => audio.resume("loop"));
      return () => {
        offPause();
        offResume();
      };
    },
    bus: (name) => buses?.[name] ?? null,
    async load(url) {
      try {
        const response = await fetcher(url);
        if (!response.ok) return null;
        const data = await response.arrayBuffer();
        const ctx = ensure();
        if (!ctx) return null;
        return await ctx.decodeAudioData(data);
      } catch {
        return null;
      }
    },
    play,
    music(buffer, musicOptions = {}) {
      musicSound?.stop();
      musicSound = null;
      if (!buffer) return;
      if (!running()) {
        pendingMusic = { buffer, options: musicOptions };
        return;
      }
      musicSound = play(buffer, { loop: true, ...musicOptions, bus: "music" });
    },
    stopMusic() {
      pendingMusic = null;
      musicSound?.stop();
      musicSound = null;
    },
    stopAll() {
      pendingMusic = null;
      for (const { sound } of [...sounds]) sound.stop();
      sounds.clear();
      musicSound = null;
    },
  };
  return audio;
}
