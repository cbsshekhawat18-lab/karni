/** Rejects with a TimeoutError when `promise` has not settled after `ms` milliseconds. */
export class TimeoutError extends Error {
  constructor(what: string, ms: number) {
    super(`${what} did not finish within ${ms} ms`);
    this.name = "TimeoutError";
  }
}

export function withTimeout<T>(promise: Promise<T>, ms: number, what: string): Promise<T> {
  if (!Number.isFinite(ms) || ms <= 0) return promise;
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new TimeoutError(what, ms)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/** Resolves with `get()` once it returns a value, polling every `everyMs`; rejects after `ms`. */
export function waitFor<T>(
  get: () => T | undefined | null,
  ms: number,
  what: string,
  everyMs = 50,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const started = Date.now();
    const check = (): void => {
      let value: T | undefined | null;
      try {
        value = get();
      } catch {
        value = undefined;
      }
      if (value !== undefined && value !== null) {
        resolve(value);
      } else if (Date.now() - started >= ms) {
        reject(new Error(`${what} is not on the page`));
      } else {
        setTimeout(check, everyMs);
      }
    };
    check();
  });
}

/** Calls `fn` and reports a throw instead of letting it reach the game. */
export function guard(fn: () => void, report: (error: unknown) => void): void {
  try {
    fn();
  } catch (error) {
    report(error);
  }
}
