import { describe, expect, it } from "vitest";
import { createAudio, createLoop } from "../src";
import { FakeAudioContext } from "./fake-audio";

const setup = (volumes = {}) => {
  const fake = new FakeAudioContext();
  const audio = createAudio({
    volumes,
    createContext: () => fake as unknown as AudioContext,
  });
  return { fake, audio };
};
const buffer = {} as AudioBuffer;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("createAudio", () => {
  it("is silent and safe before unlock, and starts on unlock", async () => {
    const { fake, audio } = setup();
    expect(audio.context).toBeNull();
    expect(audio.play(buffer)).toBeNull();
    expect(audio.bus("music")).toBeNull();
    await expect(audio.unlock()).resolves.toBe(true);
    expect(audio.unlocked).toBe(true);
    expect(fake.sources[0]?.started).toBe(true); // the silent sound inside the gesture
    const sound = audio.play(buffer, { volume: 0.5, rate: 1.2 });
    expect(sound?.playing).toBe(true);
    sound?.stop();
    expect(sound?.playing).toBe(false);
  });

  it("unlocks on the input's first gesture", async () => {
    const { audio } = setup();
    let fire: () => void = () => undefined;
    audio.unlockOn({ onFirstGesture: (callback) => (fire = callback) });
    fire();
    await flush();
    expect(audio.unlocked).toBe(true);
  });

  it("works without Web Audio at all", async () => {
    const audio = createAudio({
      createContext: () => {
        throw new Error("none");
      },
    });
    await expect(audio.unlock()).resolves.toBe(false);
    expect(audio.play(buffer)).toBeNull();
    audio.setMuted("player", true);
    audio.pause();
    await expect(audio.load("x.ogg")).resolves.toBeNull();
  });

  it("keeps master, music and effects volumes, clamped to 0..1", async () => {
    const { audio } = setup({ music: 0.4 });
    await audio.unlock();
    audio.setVolume("effects", 2);
    audio.setVolume("master", -1);
    expect(audio.volume("effects")).toBe(1);
    expect(audio.volume("master")).toBe(0);
    expect(audio.bus("music")?.gain.value).toBe(0.4);
  });

  it("keeps player, ad and portal mutes apart", async () => {
    const { audio } = setup({ master: 0.8 });
    await audio.unlock();
    const master = audio.bus("master");
    audio.setMuted("player", true);
    audio.setMuted("ad", true);
    audio.setMuted("ad", false);
    expect(audio.muted).toBe(true);
    expect(audio.isMuted("player")).toBe(true);
    expect(audio.isMuted("ad")).toBe(false);
    expect(master?.gain.value).toBe(0);
    audio.setMuted("player", false);
    expect(master?.gain.value).toBe(0.8);
    audio.setMuted("portal", true);
    expect(master?.gain.value).toBe(0);
  });

  it("suspends with the game and resumes once every reason is lifted", async () => {
    const { fake, audio } = setup();
    await audio.unlock();
    audio.pause("hidden");
    audio.pause("ad");
    await flush();
    expect(fake.state).toBe("suspended");
    audio.resume("hidden");
    await flush();
    expect(fake.state).toBe("suspended");
    audio.resume("ad");
    await flush();
    expect(fake.state).toBe("running");
  });

  it("follows a loop's pause", async () => {
    const { fake, audio } = setup();
    await audio.unlock();
    const loop = createLoop({
      update: () => undefined,
      requestFrame: () => 0,
      cancelFrame: () => undefined,
    });
    audio.follow(loop);
    loop.pause("menu");
    await flush();
    expect(fake.state).toBe("suspended");
    loop.resume("menu");
    await flush();
    expect(fake.state).toBe("running");
  });

  it("starts music asked for before unlock, and replaces the track", async () => {
    const { fake, audio } = setup();
    audio.music(buffer);
    expect(fake.sources).toHaveLength(0);
    await audio.unlock();
    const first = fake.sources.find((source) => source.loop);
    expect(first?.started).toBe(true);
    audio.music(buffer);
    expect(first?.stopped).toBe(true);
    audio.stopAll();
    expect(fake.sources.filter((source) => source.loop).every((source) => source.stopped)).toBe(
      true,
    );
  });

  it("loads and decodes, or resolves null on a missing file", async () => {
    const fake = new FakeAudioContext();
    const audio = createAudio({
      createContext: () => fake as unknown as AudioContext,
      fetch: async (url) =>
        url === "hit.ogg"
          ? new Response(new Uint8Array([1, 2, 3]))
          : new Response("", { status: 404 }),
    });
    await expect(audio.load("hit.ogg")).resolves.toEqual({ bytes: 3 });
    await expect(audio.load("missing.ogg")).resolves.toBeNull();
  });

  it("reports false when the browser refuses to start audio", async () => {
    const { fake, audio } = setup();
    fake.refuseResume = true;
    await expect(audio.unlock()).resolves.toBe(false);
  });
});
