import { describe, expect, it } from "vitest";
import { createQueue } from "../src/client/queue";
import { createStorage, memoryStorage } from "../src";

const setup = (max = 500) => {
  let clock = 1000;
  const backend = memoryStorage();
  const storage = createStorage({ namespace: "g", backend });
  const queue = createQueue({ storage, max, backoffMs: 100, now: () => clock });
  return {
    queue,
    storage,
    backend,
    tick: (ms: number) => (clock += ms),
    make: () => createQueue({ storage, now: () => clock }),
  };
};

const write = (id: string, kind = "score", key?: string) => ({
  id,
  kind,
  method: "POST" as const,
  path: `/x/${id}/`,
  body: { id },
  key,
});

describe("createQueue", () => {
  it("keeps writes across a reload, in order", () => {
    const { queue, make } = setup();
    queue.add(write("a"));
    queue.add(write("b"));
    expect(
      make()
        .list()
        .map((w) => w.id),
    ).toEqual(["a", "b"]);
  });

  it("sends in order, removes done and dropped writes, stops at a failure with backoff", async () => {
    const { queue, tick } = setup();
    for (const id of ["a", "b", "c", "d"]) queue.add(write(id));
    const sent: string[] = [];
    const result = await queue.flush(async (w) => {
      sent.push(w.id);
      if (w.id === "b") return "drop";
      if (w.id === "c") return {};
      return "done";
    });
    expect(sent).toEqual(["a", "b", "c"]);
    expect(result).toEqual({ sent: 1, dropped: 1, left: 2 });
    expect(queue.nextAt()).toBe(1100);
    // Not due yet: nothing is sent.
    expect((await queue.flush(async () => "done")).sent).toBe(0);
    tick(100);
    await queue.flush(async () => ({}));
    expect(queue.list()[0]?.attempts).toBe(2);
    expect(queue.nextAt()).toBe(1100 + 200);
    tick(200);
    expect(await queue.flush(async () => "done")).toEqual({ sent: 2, dropped: 0, left: 0 });
  });

  it("waits as long as the server asks (429 Retry-After)", async () => {
    const { queue } = setup();
    queue.add(write("a"));
    await queue.flush(async () => ({ retryInMs: 30_000 }));
    expect(queue.nextAt()).toBe(31_000);
  });

  it("treats a throwing sender as a failure to retry", async () => {
    const { queue } = setup();
    queue.add(write("a"));
    const result = await queue.flush(async () => {
      throw new Error("boom");
    });
    expect(result.left).toBe(1);
  });

  it("replaces a waiting write with the same key (the latest save of a slot)", () => {
    const { queue } = setup();
    queue.add(write("s1", "save", "save:main"));
    queue.add(write("x"));
    queue.add(write("s2", "save", "save:main"));
    expect(queue.list().map((w) => w.id)).toEqual(["s2", "x"]);
  });

  it("drops the oldest analytics first past the cap", () => {
    const { queue } = setup(3);
    queue.add(write("score-1"));
    queue.add(write("ev-1", "events"));
    queue.add(write("score-2"));
    queue.add(write("score-3"));
    expect(queue.list().map((w) => w.id)).toEqual(["score-1", "score-2", "score-3"]);
    queue.add(write("score-4"));
    expect(queue.list().map((w) => w.id)).toEqual(["score-2", "score-3", "score-4"]);
  });

  it("runs one flush at a time", async () => {
    const { queue } = setup();
    queue.add(write("a"));
    let calls = 0;
    const send = async () => {
      calls += 1;
      await new Promise((resolve) => setTimeout(resolve, 5));
      return "done" as const;
    };
    await Promise.all([queue.flush(send), queue.flush(send)]);
    expect(calls).toBe(1);
  });

  it("ignores a broken stored queue", () => {
    const { backend, make } = setup();
    backend.setItem("g.queue", JSON.stringify([{ nope: 1 }, "x"]));
    expect(make().size).toBe(0);
  });
});
