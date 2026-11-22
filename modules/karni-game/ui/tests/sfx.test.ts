import { describe, expect, it } from "vitest";
import { createAudio } from "@karni/game";
import {
  arpeggio,
  createSfx,
  envelopeAt,
  lengthOf,
  mix,
  noise,
  noiseSource,
  presets,
  renderSpec,
  sweep,
  tone,
  waveAt,
} from "@karni/game/sfx";
import { FakeAudioContext, FakeParam } from "./fake-audio";

const RATE = 8000;

describe("procedural sound", () => {
  it("shapes an envelope: attack up, decay to sustain, release to zero, never past the end", () => {
    const env = { attack: 0.1, decay: 0.1, sustain: 0.5, release: 0.2 };
    expect(envelopeAt(0, 1, env)).toBe(0);
    expect(envelopeAt(0.05, 1, env)).toBeCloseTo(0.5);
    expect(envelopeAt(0.1, 1, env)).toBeCloseTo(1);
    expect(envelopeAt(0.2, 1, env)).toBeCloseTo(0.5);
    expect(envelopeAt(0.5, 1, env)).toBe(0.5);
    expect(envelopeAt(0.9, 1, env)).toBeCloseTo(0.25);
    expect(envelopeAt(1, 1, env)).toBe(0);
    // Parts longer than the sound shrink to fit it.
    expect(envelopeAt(0.049, 0.1, { attack: 1, decay: 1, release: 1 })).toBeLessThan(1);
    expect(envelopeAt(-1, 1)).toBe(0);
  });

  it("makes each wave over one cycle", () => {
    expect(waveAt("sine", 0.25)).toBeCloseTo(1);
    expect(waveAt("square", 0.25)).toBe(1);
    expect(waveAt("square", 0.75)).toBe(-1);
    expect(waveAt("square", 0.3, 0.2)).toBe(-1);
    expect(waveAt("saw", 0)).toBe(-1);
    expect(waveAt("triangle", 0.5)).toBe(1);
    expect(waveAt("triangle", 0)).toBe(-1);
  });

  it("renders a tone at its pitch: a 1 kHz sine crosses zero 2000 times a second", () => {
    const samples = renderSpec(
      tone(1000, 1, {
        wave: "sine",
        volume: 1,
        envelope: { attack: 0, decay: 0, sustain: 1, release: 0 },
      }),
      RATE,
    );
    expect(samples.length).toBe(RATE);
    let crossings = 0;
    for (let i = 1; i < samples.length; i += 1) {
      if ((samples[i - 1] ?? 0) < 0 !== (samples[i] ?? 0) < 0) crossings += 1;
    }
    expect(crossings).toBeGreaterThan(1990);
    expect(crossings).toBeLessThan(2010);
  });

  it("slides pitch in a sweep: the second half crosses zero more often than the first", () => {
    const samples = renderSpec(sweep(200, 1600, 1, { wave: "sine", volume: 1 }), RATE);
    const crossings = (from: number, to: number): number => {
      let n = 0;
      for (let i = from + 1; i < to; i += 1) {
        if ((samples[i - 1] ?? 0) < 0 !== (samples[i] ?? 0) < 0) n += 1;
      }
      return n;
    };
    expect(crossings(RATE / 2, RATE)).toBeGreaterThan(crossings(0, RATE / 2) * 2);
  });

  it("renders noise the same every time, and darker with a low-pass", () => {
    const a = renderSpec(noise(0.2, { volume: 1 }), RATE);
    const b = renderSpec(noise(0.2, { volume: 1 }), RATE);
    expect(Array.from(a)).toEqual(Array.from(b));
    const rough = (data: Float32Array): number => {
      let sum = 0;
      for (let i = 1; i < data.length; i += 1) sum += Math.abs((data[i] ?? 0) - (data[i - 1] ?? 0));
      return sum;
    };
    const dull = renderSpec(noise(0.2, { volume: 1, lowpass: 300 }), RATE);
    expect(rough(dull)).toBeLessThan(rough(a) / 3);
    const seeded = noiseSource(7);
    expect(seeded()).not.toBe(seeded());
  });

  it("lays notes in turn in an arpeggio and layers in a mix, and keeps the sum inside full scale", () => {
    const seq = arpeggio([440, 880], 0.5, { wave: "sine", volume: 1, duration: 0.25 });
    expect(lengthOf(seq)).toBeCloseTo(0.75);
    const samples = renderSpec(seq, RATE);
    expect(samples.length).toBe(Math.round(0.75 * RATE));
    // The gap between the notes is silent.
    expect(
      Math.max(
        ...Array.from(samples.slice(Math.round(0.3 * RATE), Math.round(0.45 * RATE))).map(Math.abs),
      ),
    ).toBe(0);
    const loud = renderSpec(
      mix(tone(300, 0.1, { volume: 1 }), tone(300, 0.1, { volume: 1 })),
      RATE,
    );
    expect(Math.max(...Array.from(loud).map(Math.abs))).toBeLessThanOrEqual(1);
    expect(lengthOf(mix(tone(1, 0.2), tone(1, 0.5)))).toBe(0.5);
  });

  it("ships presets that all render something audible, with no file", () => {
    for (const [name, make] of Object.entries(presets)) {
      const samples = renderSpec(make(), 22050);
      const peak = Math.max(...Array.from(samples).map(Math.abs));
      expect(peak, name).toBeGreaterThan(0.05);
      expect(peak, name).toBeLessThanOrEqual(1);
    }
  });
});

function setup(random = () => 0.5, voices?: number) {
  const fake = new FakeAudioContext();
  const created: { length: number; data: Float32Array; duration: number }[] = [];
  fake.createBuffer = ((_channels: number, length: number, rate: number) => {
    const data = new Float32Array(length);
    const buffer = { length, duration: length / rate, getChannelData: () => data };
    created.push({ length, data, duration: buffer.duration });
    return buffer;
  }) as never;
  Object.assign(fake, { sampleRate: RATE });
  const audio = createAudio({ createContext: () => fake as unknown as AudioContext });
  const sfx = createSfx({ audio, random, voices });
  return { fake, audio, sfx, created };
}

const playParam = (fake: FakeAudioContext, index: number): FakeParam =>
  (fake.gains[index] as unknown as { gain: FakeParam }).gain;

describe("createSfx", () => {
  it("is silent until the first gesture, then renders a spec once and plays it", async () => {
    const { audio, sfx, created, fake } = setup();
    sfx.define("coin", presets.coin());
    expect(sfx.play("coin")).toBeNull();
    expect(created).toHaveLength(0);
    await audio.unlock();
    created.length = 0;
    expect(sfx.play("coin")).not.toBeNull();
    sfx.play("coin");
    expect(created).toHaveLength(1);
    expect(created[0]?.length).toBeGreaterThan(100);
    expect(Math.max(...Array.from(created[0]?.data ?? []).map(Math.abs))).toBeGreaterThan(0.05);
    expect(fake.sources.length).toBeGreaterThan(2);
    expect(sfx.play("missing")).toBeNull();
    expect(sfx.has("coin")).toBe(true);
  });

  it("varies pitch and volume within the range asked", async () => {
    const draws = [0, 1, 0.5, 0, 1, 1];
    let at = 0;
    const { audio, sfx, fake } = setup(() => draws[at++ % draws.length] ?? 0);
    await audio.unlock();
    sfx.define("hit", presets.hit());
    sfx.play("hit", { pitchVariation: 0.2, volumeVariation: 0.5, volume: 0.8 });
    const source = fake.sources.at(-1);
    expect(source?.playbackRate.value).toBeCloseTo(0.8);
    // random() = 1 for volume: the full 0.8.
    const gain = fake.gains.at(-1) as unknown as { gain: FakeParam };
    expect(gain.gain.value).toBeCloseTo(0.8);
    sfx.play("hit", { pitchVariation: 0.2, volumeVariation: 0.5, volume: 0.8 });
    expect(fake.sources.at(-1)?.playbackRate.value).toBeCloseTo(1);
    expect((fake.gains.at(-1) as unknown as { gain: FakeParam }).gain.value).toBeCloseTo(0.4);
  });

  it("limits voices per name and overall, stopping the oldest", async () => {
    const { audio, sfx, fake } = setup(() => 0.5, 3);
    await audio.unlock();
    sfx.define("a", presets.blip());
    sfx.define("b", presets.click());
    const first = sfx.play("a", { voices: 2 });
    const second = sfx.play("a", { voices: 2 });
    expect(sfx.voices).toBe(2);
    const third = sfx.play("a", { voices: 2 });
    expect(first?.playing).toBe(false);
    expect(second?.playing).toBe(true);
    expect(third?.playing).toBe(true);
    expect(sfx.voices).toBe(2);
    const b1 = sfx.play("b");
    expect(sfx.voices).toBe(3);
    sfx.play("b");
    // Four sounds would pass the overall limit of 3: the oldest, the second "a", goes.
    expect(second?.playing).toBe(false);
    expect(b1?.playing).toBe(true);
    expect(sfx.voices).toBe(3);
    sfx.stopAll();
    expect(sfx.voices).toBe(0);
    expect(fake.sources.filter((s) => !s.stopped).length).toBeLessThanOrEqual(1);
  });

  it("starts music on the first gesture, and crossfades to the next track", async () => {
    const { audio, sfx, fake } = setup();
    sfx.define("calm", tone(220, 2, { wave: "sine" }));
    sfx.define("fight", tone(330, 2, { wave: "saw" }));
    sfx.music("calm", { fade: 2, volume: 0.8 });
    expect(fake.sources).toHaveLength(0);
    await audio.unlock();
    // The first gain is the master, then music, effects (3 buses), then the track.
    const track1 = fake.sources.at(-1);
    expect(track1?.loop).toBe(true);
    const gain1 = playParam(fake, fake.gains.length - 1);
    expect(gain1.calls).toContainEqual(["linear", 0.8, 2]);
    fake.currentTime = 10;
    sfx.music("fight", { fade: 2 });
    const out = playParam(fake, fake.gains.length - 2);
    expect(out.calls).toContainEqual(["linear", 0, 12]);
    const gain2 = playParam(fake, fake.gains.length - 1);
    expect(gain2.calls).toContainEqual(["set", 0, 10]);
    expect(gain2.calls).toContainEqual(["linear", 1, 12]);
    // The old track stops once the audio clock passes its fade.
    fake.currentTime = 12.5;
    await new Promise((done) => setTimeout(done, 2300));
    expect(track1?.stopped).toBe(true);
  }, 10_000);

  it("ducks the music for a while on the audio clock, and comes back", async () => {
    const { audio, sfx, fake } = setup();
    sfx.define("calm", tone(220, 2, { wave: "sine" }));
    sfx.define("fanfare", tone(440, 1.5, { wave: "square" }));
    await audio.unlock();
    sfx.music("calm", { fade: 0 });
    const music = playParam(fake, fake.gains.length - 1);
    fake.currentTime = 5;
    sfx.play("fanfare", { duck: true });
    // Down to 0.3 in 0.05 s, held to 5.45, back up by 5.95.
    expect(music.calls.slice(-5)).toEqual([
      ["cancel", 5],
      ["set", 1, 5],
      ["linear", 0.3, 5.05],
      ["set", 0.3, 5.45],
      ["linear", 1, 5.95],
    ]);
    sfx.duck({ to: 0.5, attack: 0.1, hold: 1, release: 1 });
    const last = music.calls.slice(-3);
    // A second duck inside the first goes no higher than the lower of the two.
    expect(last[0]).toEqual(["linear", 0.3, 5.1]);
    expect(last[2]).toEqual(["linear", 1, 7.1]);
  });

  it("follows the pause: a paused game has no running context to play on", async () => {
    const { audio, sfx } = setup();
    sfx.define("a", presets.blip());
    await audio.unlock();
    audio.pause("game");
    await new Promise((done) => setTimeout(done, 0));
    expect(audio.unlocked).toBe(false);
    expect(sfx.play("a")).toBeNull();
    audio.resume("game");
    await new Promise((done) => setTimeout(done, 0));
    expect(sfx.play("a")).not.toBeNull();
  });

  it("takes a decoded buffer as a sound too, and stopMusic clears a music still waiting", async () => {
    const { audio, sfx, fake } = setup();
    const buffer = { duration: 1, length: 8, numberOfChannels: 1 } as unknown as AudioBuffer;
    sfx.define("file", buffer);
    sfx.music("file");
    sfx.stopMusic();
    await audio.unlock();
    expect(fake.sources.filter((s) => s.loop)).toHaveLength(0);
    expect(sfx.play("file")).not.toBeNull();
  });
});
