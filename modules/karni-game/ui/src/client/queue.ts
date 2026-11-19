import type { GameStorage } from "../save/storage";
import type { Method } from "./transport";

/** A write waiting to reach the server. */
export interface QueuedWrite {
  /** The intent sent with the write: a retry repeats it, so the server never counts it twice. */
  id: string;
  /** What it is ("score", "progress", "events", "save", "claim"), for listeners and the size cap. */
  kind: string;
  method: Method;
  path: string;
  body?: unknown;
  /** A newer write with the same key replaces a waiting one (the latest save of a slot). */
  key?: string;
  attempts: number;
  createdAt: number;
  /** Not sent before this time (backoff after a failure). */
  notBefore: number;
}

/** What sending one write came to. */
export type SendOutcome =
  /** The server took it: remove it. */
  | "done"
  /** The server refused it for good (out of range, unknown board): remove it. */
  | "drop"
  /** The network or the server failed: keep it and try later, after `retryInMs` when given. */
  | { retryInMs?: number };

export interface QueueOptions {
  storage: GameStorage;
  /** The storage key. Default "queue". */
  key?: string;
  /** The most writes kept. Past it the oldest analytics go first, then the oldest of any kind. */
  max?: number;
  /** The first retry waits this long, doubling to `maxBackoffMs`. Default 2000 ms. */
  backoffMs?: number;
  maxBackoffMs?: number;
  now?: () => number;
}

export interface WriteQueue {
  readonly size: number;
  list(): readonly QueuedWrite[];
  add(write: Omit<QueuedWrite, "attempts" | "createdAt" | "notBefore">): QueuedWrite;
  remove(id: string): void;
  clear(): void;
  /** The soonest time a waiting write may be sent, or null when none waits. */
  nextAt(): number | null;
  /**
   * Send the writes that are due, oldest first. A failure stops the run, so
   * writes keep their order. One run at a time: a second call waits for it.
   */
  flush(send: (write: QueuedWrite) => Promise<SendOutcome>): Promise<FlushResult>;
}

export interface FlushResult {
  sent: number;
  dropped: number;
  left: number;
}

const isWrite = (value: unknown): value is QueuedWrite =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as QueuedWrite).id === "string" &&
  typeof (value as QueuedWrite).path === "string";

/** A write queue kept in the game's storage, so writes made offline survive a reload. */
export function createQueue(options: QueueOptions): WriteQueue {
  const { storage } = options;
  const key = options.key ?? "queue";
  const max = options.max ?? 500;
  const backoffMs = options.backoffMs ?? 2000;
  const maxBackoffMs = options.maxBackoffMs ?? 5 * 60_000;
  const now = options.now ?? Date.now;
  const stored = storage.getJson<unknown[]>(key);
  let writes: QueuedWrite[] = Array.isArray(stored) ? stored.filter(isWrite) : [];
  let running: Promise<FlushResult> | null = null;

  const persist = (): void => {
    storage.setJson(key, writes);
  };

  const trim = (): void => {
    while (writes.length > max) {
      const analytics = writes.findIndex((write) => write.kind === "events");
      writes.splice(analytics >= 0 ? analytics : 0, 1);
    }
  };

  const run = async (send: (write: QueuedWrite) => Promise<SendOutcome>): Promise<FlushResult> => {
    let sent = 0;
    let dropped = 0;
    for (;;) {
      const write = writes[0];
      if (!write || write.notBefore > now()) break;
      let outcome: SendOutcome;
      try {
        outcome = await send(write);
      } catch {
        outcome = {};
      }
      if (outcome === "done" || outcome === "drop") {
        writes = writes.filter((other) => other.id !== write.id);
        if (outcome === "done") sent += 1;
        else dropped += 1;
        persist();
        continue;
      }
      write.attempts += 1;
      const wait =
        outcome.retryInMs ?? Math.min(maxBackoffMs, backoffMs * 2 ** (write.attempts - 1));
      write.notBefore = now() + wait;
      persist();
      break;
    }
    return { sent, dropped, left: writes.length };
  };

  return {
    get size() {
      return writes.length;
    },
    list: () => writes,
    add(write) {
      const queued: QueuedWrite = { ...write, attempts: 0, createdAt: now(), notBefore: 0 };
      if (write.key) {
        const waiting = writes.findIndex((other) => other.key === write.key);
        if (waiting >= 0) {
          writes[waiting] = queued;
          persist();
          return queued;
        }
      }
      writes.push(queued);
      trim();
      persist();
      return queued;
    },
    remove(id) {
      writes = writes.filter((write) => write.id !== id);
      persist();
    },
    clear() {
      writes = [];
      persist();
    },
    nextAt() {
      const first = writes[0];
      return first ? first.notBefore : null;
    },
    async flush(send) {
      while (running) await running;
      running = run(send);
      try {
        return await running;
      } finally {
        running = null;
      }
    },
  };
}
