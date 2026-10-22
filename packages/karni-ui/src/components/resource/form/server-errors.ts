/**
 * DRF validation bodies → the fields they belong to.
 *
 * DRF answers a failed save with many shapes, and ResourceForm must put every
 * message where the user can act on it:
 *
 *   {"title": ["Required."]}                       a field
 *   {"title": "Required."}                         a field, one message
 *   {"address": {"city": ["Required."]}}           a nested serializer
 *   {"items": [{}, {"name": ["Required."]}]}       a list serializer
 *   {"tags": {"1": ["Invalid pk."]}}               errors keyed by position
 *   {"non_field_errors": ["..."]}, {"detail": "..."}, ["..."], "..."
 *   {"secret_field": ["..."]}                      a key the form does not show
 *
 * A message lands on the deepest path the form renders (`address.city` when
 * that is a field, else `address` with the nested part named in the
 * message). Everything else is a form-level message that names what it
 * is about. Internal to @karni/ui.
 */
import { humanizeValue } from "./prepare";

export interface MappedServerErrors {
  /** Field path → its messages, joined into one sentence run. */
  fields: Record<string, string>;
  /** Messages that belong to no field the form shows. */
  root: string[];
}

export interface MapServerErrorsOptions {
  /** Whether the form renders an input for `path` ("title", "address.city"). */
  isField: (path: string) => boolean;
  /** How a path is named in a form-level message. The default humanizes it. */
  labelOf?: (path: string) => string;
}

const ROOT_KEYS = new Set(["non_field_errors", "detail", "__all__"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function defaultLabel(path: string): string {
  const segments = path.split(".");
  const named = segments.map((segment) =>
    /^\d+$/.test(segment) ? `item ${Number(segment) + 1}` : segment,
  );
  return humanizeValue(named.join(" "));
}

/** Every message inside `value`, nested parts prefixed with what they are about. */
function messagesOf(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (typeof value === "string") return value.trim() === "" ? [] : [value];
  if (typeof value === "number" || typeof value === "boolean") return [String(value)];
  if (Array.isArray(value)) {
    return value.flatMap((entry, index) =>
      isRecord(entry) && !("message" in entry)
        ? messagesOf(entry).map((message) => `Item ${index + 1}: ${message}`)
        : messagesOf(entry),
    );
  }
  if (isRecord(value)) {
    // {"message": "...", "code": "..."} (DRF's get_full_details shape).
    if (typeof value["message"] === "string") return [value["message"]];
    return Object.entries(value).flatMap(([key, nested]) =>
      messagesOf(nested).map((message) =>
        ROOT_KEYS.has(key) ? message : `${defaultLabel(key)}: ${message}`,
      ),
    );
  }
  return [];
}

/** True for HTML error pages and other bodies that are not a message for people. */
function isMarkup(text: string): boolean {
  return /^\s*</.test(text);
}

/** Splits a DRF error body into field messages and form-level messages. */
export function mapServerErrors(
  data: unknown,
  { isField, labelOf = defaultLabel }: MapServerErrorsOptions,
): MappedServerErrors {
  const fields: Record<string, string[]> = {};
  const root: string[] = [];

  const toRoot = (path: string, value: unknown): void => {
    for (const message of messagesOf(value)) root.push(`${labelOf(path)}: ${message}`);
  };

  const walk = (path: string, value: unknown): void => {
    if (isField(path)) {
      const messages = messagesOf(value);
      if (messages.length > 0) (fields[path] ??= []).push(...messages);
      return;
    }
    if (isRecord(value) && typeof value["message"] !== "string") {
      for (const [key, nested] of Object.entries(value)) {
        if (ROOT_KEYS.has(key)) root.push(...messagesOf(nested));
        else walk(`${path}.${key}`, nested);
      }
      return;
    }
    if (Array.isArray(value) && value.some(isRecord)) {
      value.forEach((entry, index) => {
        if (isRecord(entry)) walk(`${path}.${index}`, entry);
        else toRoot(path, entry);
      });
      return;
    }
    toRoot(path, value);
  };

  if (typeof data === "string") {
    if (data.trim() !== "" && !isMarkup(data)) root.push(data.trim());
  } else if (Array.isArray(data)) {
    root.push(...messagesOf(data));
  } else if (isRecord(data)) {
    for (const [key, value] of Object.entries(data)) {
      if (ROOT_KEYS.has(key)) {
        root.push(...messagesOf(value));
      } else if (key === "code" && typeof value === "string" && "detail" in data) {
        // {"detail": "...", "code": "..."}: the code is for programs, not people.
        continue;
      } else {
        walk(key, value);
      }
    }
  }

  return {
    fields: Object.fromEntries(
      Object.entries(fields).map(([path, messages]) => [path, messages.join(" ")]),
    ),
    root,
  };
}
