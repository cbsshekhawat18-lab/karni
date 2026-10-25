/**
 * ResourceDetail's lifecycle buttons: one per state the record may move to.
 *
 * A StateField publishes `x-karni-transitions` (state → next states) in the
 * schema. For each such field the API lets this user write, the buttons are
 * the next states of the record's current state, and a click PATCHes the
 * field: the API's own transition, which the server checks again (an illegal
 * move is a 400, a concurrent one a 409, both shown in plain words).
 *
 * Internal to @karni/ui. The public surface is ResourceDetail's `transitions`
 * prop and its `Transitions` slot.
 */
import * as React from "react";
import { KarniApiError } from "../../../schema/client";
import type { FieldDef } from "../../../schema/types";
import { describeError } from "../../../states/describe-error";
import { PendingButton } from "../../../states/PendingButton";
import { Modal, ModalClose } from "../../modal/modal";
import { Button } from "../../primitives/button";
import { AlertIcon } from "../../primitives/icons";
import { humanizeValue } from "../form/prepare";

type Item = Record<string, unknown>;

/** Tunes the lifecycle buttons. `transitions={false}` on ResourceDetail hides them. */
export interface ResourceDetailTransitionOptions {
  /** Only these lifecycle fields. Default: every field the schema marks with transitions. */
  fields?: readonly string[];
  /** Button text per target state, e.g. `{ cancelled: "Cancel order" }`. Default: "Mark as <state>". */
  labels?: Readonly<Record<string, string>>;
  /**
   * Target states that ask before moving. Default: the terminal ones (nothing
   * leaves them, so the move cannot be undone). `true` asks for every move,
   * `false` for none.
   */
  confirm?: boolean | readonly string[];
  /** Whether this user may make this move. Default: the update operation's access rule. */
  can?: (item: Item, field: string, target: string) => boolean;
}

/** One state a record may move to, as the `Transitions` slot receives it. */
export interface ResourceDetailTransitionTarget {
  /** The state's value ("confirmed"). */
  value: string;
  /** The state in words ("Confirmed"). */
  label: string;
  /** The button text ("Mark as Confirmed", or `labels[value]`). */
  action: string;
  /** Nothing leaves this state. */
  terminal: boolean;
}

/** What the `Transitions` slot receives: the buttons of one lifecycle field. */
export interface ResourceDetailTransitionsProps {
  field: FieldDef;
  item: Item;
  /** The record's state now. */
  current: string;
  /** The state now, in words. */
  currentLabel: string;
  /** The states it may move to, in the schema's order. */
  targets: readonly ResourceDetailTransitionTarget[];
  /** Moves the record (after the confirmation, when the target asks for one). */
  onMove: (target: string) => void;
  /** The target being saved, or null. */
  pending: string | null;
}

export function stateLabel(field: FieldDef, value: string): string {
  return field.enumLabels?.[value] ?? humanizeValue(value);
}

function askFirst(
  confirm: ResourceDetailTransitionOptions["confirm"],
  target: ResourceDetailTransitionTarget,
): boolean {
  if (confirm === undefined) return target.terminal;
  if (typeof confirm === "boolean") return confirm;
  return confirm.includes(target.value);
}

/** The default `Transitions` slot: a button per target, the first open state as the main one. */
export function DefaultTransitions(props: ResourceDetailTransitionsProps): React.ReactElement {
  const { field, targets, onMove, pending } = props;
  const main = targets.find((target) => !target.terminal)?.value;
  return (
    <div role="group" aria-label={`Change ${field.label.toLowerCase()}`} className="contents">
      {targets.map((target) => (
        <PendingButton
          key={target.value}
          variant={target.value === main ? "default" : "outline"}
          pending={pending === target.value}
          pendingLabel="Saving…"
          disabled={pending !== null}
          data-transition={target.value}
          onClick={() => onMove(target.value)}
        >
          {target.action}
        </PendingButton>
      ))}
    </div>
  );
}

/** The targets of one field for this record, or null when it shows no buttons. */
export function transitionTargets(
  field: FieldDef,
  item: Item,
  options: ResourceDetailTransitionOptions,
): { current: string; targets: ResourceDetailTransitionTarget[] } | null {
  const transitions = field.transitions;
  if (transitions === undefined || field.readOnly || !(field.name in item)) return null;
  const current = item[field.name];
  if (typeof current !== "string" || !(current in transitions)) return null;
  const targets = (transitions[current] ?? [])
    .filter((target) => options.can === undefined || options.can(item, field.name, target))
    .map((value) => {
      const label = stateLabel(field, value);
      return {
        value,
        label,
        action: options.labels?.[value] ?? `Mark as ${label}`,
        terminal: (transitions[value] ?? []).length === 0,
      };
    });
  return targets.length > 0 ? { current, targets } : null;
}

/** The server's own words for a refused move (the field's message), else describeError's. */
export function transitionError(error: unknown, fieldName: string): string {
  if (error instanceof KarniApiError && typeof error.data === "object" && error.data !== null) {
    const messages = (error.data as Record<string, unknown>)[fieldName];
    const first = Array.isArray(messages) ? messages[0] : messages;
    if (typeof first === "string" && first.trim() !== "") {
      // "E980: Order 3f2a…: status cannot go from … See https://…": the sentence, not the link.
      return first.replace(/\s*See https?:\/\/\S+\s*$/, "").replace(/^[A-Z]+\d+:\s*/, "");
    }
  }
  const described = describeError(error, { action: "change", resource: "this record" });
  return `${described.title}. ${described.description}`;
}

/** The inline message under the header after a move failed. */
export function TransitionFailure(props: { message: string; title: string }): React.ReactElement {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
    >
      <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="space-y-0.5">
        <p className="font-medium text-foreground">{props.title}</p>
        <p className="text-muted-foreground">{props.message}</p>
      </div>
    </div>
  );
}

/** The question before a move that asks first (by default, a move into a terminal state). */
export function TransitionConfirm(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  resourceLabel: string;
  field: FieldDef;
  currentLabel: string;
  target: ResourceDetailTransitionTarget;
  pending: boolean;
  onConfirm: () => void;
}): React.ReactElement {
  const { open, onOpenChange, resourceLabel, field, currentLabel, target, pending, onConfirm } =
    props;
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`${target.action}?`}
      description={
        target.terminal
          ? `The ${field.label.toLowerCase()} of this ${resourceLabel} goes from ${currentLabel} to ${target.label}. Nothing moves it out of ${target.label} afterwards.`
          : `The ${field.label.toLowerCase()} of this ${resourceLabel} goes from ${currentLabel} to ${target.label}.`
      }
      footer={
        <>
          <ModalClose asChild>
            <Button variant="outline" disabled={pending}>
              Keep it {currentLabel}
            </Button>
          </ModalClose>
          <PendingButton
            variant={target.terminal ? "destructive" : "default"}
            pending={pending}
            pendingLabel="Saving…"
            onClick={onConfirm}
          >
            {target.action}
          </PendingButton>
        </>
      }
    />
  );
}

export { askFirst };
