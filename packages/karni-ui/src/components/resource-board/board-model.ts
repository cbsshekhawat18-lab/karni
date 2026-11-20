/**
 * The pure part of ResourceBoard: which columns a state field gives, which
 * moves a row may make and how, and the sum of a money field.
 *
 * Internal to @karni/ui.
 */
import type { FieldDef, ResourceSchema } from "../../schema/types";
import { evaluateAccess, type AccessIdentity } from "../resource/table/access";

type Row = Readonly<Record<string, unknown>>;

/** One column of the board: a state's value and its words. */
export interface BoardColumnDef {
  value: string;
  label: string;
  /** Nothing leaves this state. */
  terminal: boolean;
}

/** How a legal move is made: a PATCH of the state field, or a declared row action. */
export type BoardMove = { via: "patch" } | { via: "action"; action: string };

/** The state field the board is by: the named one, else the first with transitions or choices. */
export function boardField(
  schema: Pick<ResourceSchema, "fields">,
  name: string | undefined,
): FieldDef | undefined {
  if (name !== undefined) return schema.fields.find((field) => field.name === name);
  return (
    schema.fields.find((field) => field.transitions !== undefined) ??
    schema.fields.find((field) => field.kind === "enum" && field.enumValues !== undefined)
  );
}

function humanize(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced === "" ? value : spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The states in the order the machine flows: from the initial states along
 * the transitions, each state as far along as its longest way in (a way back,
 * such as a reopen, does not count), states the flow never reaches after
 * those, and the closed states (no way out) last. The declared order of the
 * choices only breaks ties.
 */
export function flowOrder(
  known: readonly string[],
  transitions: Readonly<Record<string, readonly string[]>>,
  initial: readonly string[] | undefined,
): string[] {
  const declared = new Map(known.map((value, index) => [value, index]));
  const byDeclared = (a: string, b: string): number =>
    (declared.get(a) ?? 0) - (declared.get(b) ?? 0);
  const targets = (value: string): string[] =>
    (transitions[value] ?? []).filter((target) => declared.has(target)).sort(byDeclared);
  const entered = new Set(known.flatMap(targets));
  let starts = (initial ?? []).filter((value) => declared.has(value));
  if (starts.length === 0) starts = known.filter((value) => !entered.has(value));
  if (starts.length === 0) starts = known.slice(0, 1);

  // A walk from the starts: an edge back to a state still on the walk is a
  // way back and is left out, so what remains has no loop.
  const seen = new Map<string, "walking" | "done">();
  const forward = new Map<string, string[]>();
  const finished: string[] = [];
  const walk = (value: string): void => {
    seen.set(value, "walking");
    const ahead: string[] = [];
    for (const target of targets(value)) {
      const state = seen.get(target);
      if (state === "walking") continue;
      ahead.push(target);
      if (state === undefined) walk(target);
    }
    forward.set(value, ahead);
    seen.set(value, "done");
    finished.push(value);
  };
  for (const start of [...starts].sort(byDeclared)) if (!seen.has(start)) walk(start);

  const step = new Map<string, number>(finished.map((value) => [value, 0]));
  for (const value of [...finished].reverse()) {
    for (const target of forward.get(value) ?? []) {
      step.set(target, Math.max(step.get(target) ?? 0, (step.get(value) ?? 0) + 1));
    }
  }
  const closed = (value: string): number => ((transitions[value] ?? []).length === 0 ? 1 : 0);
  return [...known].sort(
    (a, b) =>
      closed(a) - closed(b) ||
      (step.get(a) ?? Infinity) - (step.get(b) ?? Infinity) ||
      byDeclared(a, b),
  );
}

/**
 * The columns, in the order the state machine flows (see `flowOrder`), or in
 * the order of the field's choices when it has no transitions. `only` keeps
 * some of them, in the order given.
 */
export function boardColumns(field: FieldDef, only?: readonly string[]): BoardColumnDef[] {
  const choices: string[] =
    field.enumValues !== undefined
      ? field.enumValues.map(String)
      : Object.keys(field.transitions ?? {});
  const known =
    field.transitions !== undefined
      ? flowOrder(choices, field.transitions, field.initial)
      : choices;
  const values = only !== undefined ? only.filter((value) => known.includes(value)) : known;
  return values.map((value) => ({
    value,
    label: field.enumLabels?.[value] ?? humanize(value),
    terminal: field.transitions !== undefined && (field.transitions[value] ?? []).length === 0,
  }));
}

/** The first declared row action that moves `field` from `current` to `target`, by name. */
function actionFor(
  schema: Pick<ResourceSchema, "rowActions">,
  field: string,
  current: string,
  target: string,
): string | undefined {
  for (const [name, action] of Object.entries(schema.rowActions ?? {})) {
    if (action.field !== field || action.to !== target) continue;
    if (action.from.length === 0 || action.from.includes(current)) return name;
  }
  return undefined;
}

/**
 * How `row` may move to `target`, or `null` when it may not. A move is legal
 * when the schema's `x-karni-transitions` lists it. When a declared row
 * action (`x-karni-actions`) makes that move it is the way (its `by` rule is
 * checked), else the state field is PATCHed, which needs the field to be
 * writable and the update rule not to refuse. The server checks it all again.
 */
export function resolveMove(
  schema: Pick<ResourceSchema, "rowActions" | "operations">,
  field: FieldDef,
  row: Row,
  target: string,
  identity: AccessIdentity | null,
): BoardMove | null {
  const current = row[field.name];
  if (typeof current !== "string" || current === target) return null;
  const transitions = field.transitions;
  if (transitions !== undefined && !(transitions[current] ?? []).includes(target)) return null;
  const name = actionFor(schema, field.name, current, target);
  if (name !== undefined) {
    const by = schema.rowActions?.[name]?.by ?? undefined;
    if (by !== undefined && evaluateAccess(by, identity, row) === false) return null;
    return { via: "action", action: name };
  }
  if (field.readOnly) return null;
  if (evaluateAccess(schema.operations.update?.access, identity, row) === false) return null;
  return transitions === undefined ? null : { via: "patch" };
}

const SCALE = 8;

/** A decimal string as scaled integer units, or null when it is not a plain decimal. */
function units(value: unknown): bigint | null {
  const text = typeof value === "number" ? String(value) : value;
  if (typeof text !== "string") return null;
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(text.trim());
  if (match === null) return null;
  const fraction = (match[3] ?? "").slice(0, SCALE).padEnd(SCALE, "0");
  const whole = BigInt(`${match[2] ?? "0"}${fraction}`);
  return match[1] === "-" ? -whole : whole;
}

/** The sum of a decimal field over rows, exact (no float error), as a number. Rows without one add nothing. */
export function sumField(rows: readonly Row[], name: string): number {
  let total = 0n;
  for (const row of rows) total += units(row[name]) ?? 0n;
  return Number(total) / 10 ** SCALE;
}
