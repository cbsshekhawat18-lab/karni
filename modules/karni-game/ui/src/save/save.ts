import type { GameStorage } from "./storage";

/** What a save looks like in storage: the schema version, when it was written, the data. */
export interface SaveEnvelope<T> {
  v: number;
  savedAt: string;
  data: T;
}

/** A step from one schema version to the next: `migrations[1]` turns version 1 data into version 2. */
export type Migration = (data: unknown) => unknown;

export interface SaveOptions<T> {
  storage: GameStorage;
  /** The key inside the storage's namespace. Default "save". */
  key?: string;
  /** The schema version this build writes, a whole number from 1. */
  version: number;
  /** A fresh save: a new player, or what a corrupt save is replaced with. */
  defaults: () => T;
  /**
   * Ordered steps by the version they upgrade from. `migrations[0]` adopts a
   * save written before versioning (a bare JSON value).
   */
  migrations?: Readonly<Record<number, Migration>>;
  /**
   * Check and clean loaded data, after migrations. Throw to reject it as
   * corrupt. Default: a plain object is merged over the defaults, so fields
   * added later get their default value; anything else is used as it is.
   */
  validate?: (data: unknown, defaults: T) => T;
  /** How many corrupt copies to keep beside the save. Default 3. */
  keepCorrupt?: number;
  now?: () => Date;
}

export type LoadStatus =
  /** Nothing was saved: the defaults. */
  | "new"
  /** The save was read at this build's version. */
  | "loaded"
  /** An older save was upgraded through the migrations. */
  | "migrated"
  /** The save could not be read: the defaults, and the bad copy kept under `backupKey`. */
  | "corrupt"
  /** A newer build wrote it: the defaults, and the save kept under `backupKey`. */
  | "newer";

export interface LoadResult<T> {
  data: T;
  status: LoadStatus;
  /** The version the save had in storage. */
  fromVersion?: number;
  /** Where the unreadable or newer copy was kept. */
  backupKey?: string;
  error?: unknown;
}

export interface Save<T> {
  readonly key: string;
  readonly version: number;
  /** Read the save. Never throws: a broken save boots with the defaults. */
  load(): LoadResult<T>;
  /** Write `data` at this build's version. False when storage refused it. */
  write(data: T): boolean;
  /** The envelope `write` stores, for a cloud copy. */
  envelope(data: T): SaveEnvelope<T>;
  /** Remove the save (the corrupt copies stay). */
  clear(): void;
  /** Keys of the kept corrupt or newer copies, oldest first. */
  backups(): string[];
  /** Upgrade and check data from elsewhere (a cloud slot) the way `load` does. */
  upgrade(data: unknown, fromVersion: number): T;
}

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isEnvelope = (value: unknown): value is SaveEnvelope<unknown> =>
  isPlainObject(value) && Number.isInteger(value.v) && "data" in value;

function defaultValidate<T>(data: unknown, defaults: T): T {
  if (isPlainObject(defaults) && isPlainObject(data)) return { ...defaults, ...data } as T;
  if (isPlainObject(defaults) && !isPlainObject(data)) {
    throw new Error("the save is not an object");
  }
  return data as T;
}

/**
 * A versioned save with ordered migrations, on any {@link GameStorage}. A
 * save that does not parse, fails a migration or fails `validate` never
 * stops the game: it boots with the defaults and the bad copy is kept.
 */
export function createSave<T>(options: SaveOptions<T>): Save<T> {
  const { storage } = options;
  const key = options.key ?? "save";
  const version = options.version;
  if (!Number.isInteger(version) || version < 1) {
    throw new Error("createSave: version must be a whole number from 1");
  }
  const migrations = options.migrations ?? {};
  const validate = options.validate ?? defaultValidate;
  const keepCorrupt = Math.max(1, options.keepCorrupt ?? 3);
  const now = options.now ?? (() => new Date());
  const backupPrefix = `${key}.backup.`;

  const backups = (): string[] =>
    storage
      .keys()
      .filter((name) => name.startsWith(backupPrefix))
      .sort();

  const keep = (raw: string): string => {
    const existing = backups();
    const latest = existing[existing.length - 1];
    if (latest && storage.get(latest) === raw) return latest;
    const stamp = `${backupPrefix}${now().toISOString().replace(/[:.]/g, "-")}`;
    let name = stamp;
    for (let n = 1; storage.get(name) !== null; n += 1) name = `${stamp}-${n}`;
    storage.set(name, raw);
    for (const old of backups().slice(0, -keepCorrupt)) storage.remove(old);
    return name;
  };

  const upgrade = (data: unknown, fromVersion: number): T => {
    let current = data;
    for (let at = fromVersion; at < version; at += 1) {
      const step = migrations[at];
      if (!step) throw new Error(`no migration from version ${at} to ${at + 1}`);
      current = step(current);
    }
    return validate(current, options.defaults());
  };

  const save: Save<T> = {
    key,
    version,
    load() {
      const raw = storage.get(key);
      if (raw === null) return { data: options.defaults(), status: "new" };
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch (error) {
        return { data: options.defaults(), status: "corrupt", backupKey: keep(raw), error };
      }
      const from = isEnvelope(parsed) ? parsed.v : 0;
      const body = isEnvelope(parsed) ? parsed.data : parsed;
      if (from > version) {
        return {
          data: options.defaults(),
          status: "newer",
          fromVersion: from,
          backupKey: keep(raw),
        };
      }
      try {
        const data = upgrade(body, from);
        return { data, status: from === version ? "loaded" : "migrated", fromVersion: from };
      } catch (error) {
        return {
          data: options.defaults(),
          status: "corrupt",
          fromVersion: from,
          backupKey: keep(raw),
          error,
        };
      }
    },
    envelope: (data) => ({ v: version, savedAt: now().toISOString(), data }),
    write: (data) => storage.setJson(key, save.envelope(data)),
    clear: () => storage.remove(key),
    backups,
    upgrade,
  };
  return save;
}
