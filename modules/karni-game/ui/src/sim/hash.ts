/**
 * A canonical text for plain data and a hash of it. The text is the same on
 * every machine and engine: keys are sorted, numbers use the shortest text
 * that reads back to the same double (fixed by the language), and `-0` is `0`.
 */

/** Why a value is not plain data, or null. Plain data is what JSON holds, plus NaN and Infinity. */
export function describePlain(value: unknown, path = "state"): string | null {
  const seen = new Set<object>();
  const walk = (item: unknown, where: string): string | null => {
    switch (typeof item) {
      case "string":
      case "number":
      case "boolean":
        return null;
      case "undefined":
        return null;
      case "bigint":
      case "function":
      case "symbol":
        return `${where} is a ${typeof item}, which is not plain data`;
      default:
        break;
    }
    if (item === null) return null;
    const object = item as object;
    if (seen.has(object)) return `${where} points back into itself`;
    const proto = Object.getPrototypeOf(object) as unknown;
    if (Array.isArray(object)) {
      seen.add(object);
      for (let index = 0; index < object.length; index += 1) {
        const problem = walk(object[index], `${where}[${index}]`);
        if (problem) return problem;
      }
      seen.delete(object);
      return null;
    }
    if (proto !== Object.prototype && proto !== null) {
      const name = (proto as { constructor?: { name?: string } }).constructor?.name ?? "an object";
      return `${where} is ${name}, not a plain object or array`;
    }
    seen.add(object);
    for (const key of Object.keys(object)) {
      const problem = walk((object as Record<string, unknown>)[key], `${where}.${key}`);
      if (problem) return problem;
    }
    seen.delete(object);
    return null;
  };
  return walk(value, path);
}

/** The canonical text of plain data. Throws on a value that is not plain data. */
export function canonical(value: unknown): string {
  const problem = describePlain(value);
  if (problem) throw new Error(`karni sim: ${problem}`);
  return write(value);
}

function write(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number") return Object.is(value, -0) ? "0" : String(value);
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return `[${value.map(write).join(",")}]`;
  const record = value as Record<string, unknown>;
  const parts: string[] = [];
  for (const key of Object.keys(record).sort()) {
    if (record[key] === undefined) continue;
    parts.push(`${JSON.stringify(key)}:${write(record[key])}`);
  }
  return `{${parts.join(",")}}`;
}

/** A 64-bit hash of text as 16 hex digits (two 32-bit lanes). Not a secret: it detects change, not tampering. */
export function hashText(text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    h1 = Math.imul(h1 ^ code, 2654435761);
    h2 = Math.imul(h2 ^ code, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h2 >>> 0).toString(16).padStart(8, "0") + (h1 >>> 0).toString(16).padStart(8, "0");
}

/** The hash of plain data: the same value gives the same 16 hex digits on every machine. */
export function hashState(value: unknown): string {
  return hashText(canonical(value));
}

/** The path of the first NaN or infinite number in plain data, or null. */
export function findNonFinite(value: unknown, path = "state"): string | null {
  if (typeof value === "number") return Number.isFinite(value) ? null : `${path} is ${value}`;
  if (value === null || typeof value !== "object") return null;
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = findNonFinite(value[index], `${path}[${index}]`);
      if (found) return found;
    }
    return null;
  }
  for (const key of Object.keys(value)) {
    const found = findNonFinite((value as Record<string, unknown>)[key], `${path}.${key}`);
    if (found) return found;
  }
  return null;
}
