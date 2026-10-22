/**
 * Reads an operation's `x-karni-access` rule against the signed-in user, so
 * ResourceTable leaves out the actions a role cannot perform (create, edit,
 * delete) instead of offering a button that ends in "You can't".
 *
 * The rule is the backend's own predicate, published per operation:
 * `{"public": true}`, `{"authenticated": true}`, `{"role": [...]}`,
 * `{"owned": "organizer"}`, `{"any": [...]}`, `{"all": [...]}`, `{"deny": ...}`
 * and predicates only the server can answer (`can`, `granted`, `where`,
 * `unscoped`). The answer is three-valued. It is `false` only when the rule
 * certainly refuses, and `undefined` when the client cannot tell (no
 * AuthProvider, a grant, a custom function). `undefined` keeps the action:
 * the server still enforces, and a refusal is then reported in plain words.
 *
 * Internal to @karni/ui. Escape hatch: ResourceTable's `canCreate`,
 * `canEdit` and `canDelete` props replace this evaluation.
 */
import type { KarniUser } from "../../../auth/types";
import type { KarniAccessRule } from "../../../schema/types";
import { asRecord } from "./table-utils";

/** Who is asking. `null` when the table renders outside an AuthProvider. */
export interface AccessIdentity {
  status: "loading" | "authenticated" | "anonymous";
  user: KarniUser | null;
}

const LOOKUP_SEPARATOR = "__";

function sameId(value: unknown, id: string | number): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "object" && !Array.isArray(value)) {
    return sameId(asRecord(value)["id"], id);
  }
  return String(value) === String(id);
}

/** `Owned("organizer")` on one row: is the row's owner field the user? */
function ownedBy(path: string, identity: AccessIdentity, row: unknown): boolean | undefined {
  if (identity.status !== "authenticated" || identity.user === null) {
    return identity.status === "anonymous" ? false : undefined;
  }
  // A traversal ("event__organizer") is not in the row: only the server knows.
  if (row === undefined || path.includes(LOOKUP_SEPARATOR)) return undefined;
  const record = asRecord(row);
  const key = path === "pk" ? "id" : path;
  if (!(key in record)) return undefined;
  const value = record[key];
  const userId = identity.user.id;
  return Array.isArray(value) ? value.some((item) => sameId(item, userId)) : sameId(value, userId);
}

function combine(
  parts: readonly unknown[],
  identity: AccessIdentity | null,
  row: unknown,
  any: boolean,
): boolean | undefined {
  let unknownSeen = false;
  for (const part of parts) {
    const answer = evaluateAccess(asRecord(part), identity, row);
    if (answer === any) return any;
    if (answer === undefined) unknownSeen = true;
  }
  return unknownSeen ? undefined : !any;
}

/**
 * `true` when the rule allows the operation for this identity (and row),
 * `false` when it refuses, `undefined` when only the server can tell.
 */
export function evaluateAccess(
  rule: KarniAccessRule | undefined,
  identity: AccessIdentity | null,
  row?: unknown,
): boolean | undefined {
  if (rule === undefined) return undefined;
  if (rule["public"] === true) return true;
  if ("deny" in rule) return false;
  if (Array.isArray(rule["any"])) return combine(rule["any"], identity, row, true);
  if (Array.isArray(rule["all"])) return combine(rule["all"], identity, row, false);
  if (identity === null || identity.status === "loading") return undefined;
  if (rule["authenticated"] === true) return identity.status === "authenticated";
  const roles = rule["role"];
  if (Array.isArray(roles)) {
    if (identity.status !== "authenticated" || identity.user === null) return false;
    const held = new Set(identity.user.roles);
    return roles.some((name) => typeof name === "string" && held.has(name));
  }
  const owned = rule["owned"];
  if (typeof owned === "string") return ownedBy(owned, identity, row);
  return undefined;
}
