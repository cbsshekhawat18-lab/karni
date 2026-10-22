/**
 * The states <ResourceForm> shows around its fields, as replaceable slots:
 * the loading skeleton, the permission panel, the error summary after a
 * failed submit and the banner for a submit that failed for another reason.
 * Their defaults are exported (`defaultResourceFormSlots`) so a project can
 * wrap them rather than rewrite them.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import type { FieldDef } from "../../../schema/types";
import { ErrorState, PermissionDenied, type ErrorSlotProps } from "../../../states/ErrorState";
import { describeError, type KarniErrorKind } from "../../../states/describe-error";
import { PendingButton } from "../../../states/PendingButton";
import { FileUpload } from "../../file-upload/FileUpload";
import { AlertIcon, LockIcon, OfflineIcon } from "../../primitives/icons";
import { Button } from "../../primitives/button";
import { Input } from "../../primitives/input";
import { Label } from "../../primitives/label";
import { Skeleton } from "../../primitives/skeleton";
import { Switch } from "../../primitives/switch";
import { Textarea } from "../../primitives/textarea";

/**
 * A field's label-to-control gap as Tailwind 3's `space-y` draws it: a top
 * margin on every child after the first. Tailwind 4's `space-y` puts a bottom
 * margin on the inline <label> instead, which an inline element ignores, so
 * the gap is spelled out to render the same under both.
 */
export const FIELD_GAP = "[&>:not([hidden])~:not([hidden])]:mt-2";

/** The submit row, shared by the form and its skeleton so nothing moves when the form arrives. */
export const SUBMIT_ROW = "flex items-center justify-end gap-3 pt-2";

export interface ResourceFormLoadingProps {
  /**
   * The fields the form will render, labels already overridden, once the
   * schema is known (edit mode while the row loads). Undefined while the
   * schema itself loads.
   */
  fields?: readonly FieldDef[];
  /** "create" or "update". */
  mode: "create" | "update";
  /** The submit button's label, so the skeleton's button has the real one's width. */
  submitLabel: React.ReactNode;
  /** False when the form's `actions` prop replaces the submit row. */
  showSubmitRow: boolean;
}

export interface ResourceFormForbiddenProps {
  /** The verb the role lacks: "edit". */
  action: string;
  /** What it applies to: "this event". */
  resource: string;
}

/** One entry of the error summary. */
export interface ResourceFormFieldError {
  /** The field's name. Absent for a message that belongs to no field. */
  name?: string;
  /** The field's label, as the form shows it. */
  label?: string;
  message: string;
  /** Moves focus to the field's input. Absent for a message that belongs to no field. */
  focus?: () => void;
  /** `#<the input's id>`, for a link to the field. */
  href?: string;
}

export interface ResourceFormErrorSummaryProps {
  /** "2 fields need attention", or what failed when no field did. */
  title: string;
  errors: readonly ResourceFormFieldError[];
}

export interface ResourceFormSubmitErrorProps extends ErrorSlotProps {
  /** Edit mode, after a conflict: loads the latest version of the row (typed values are kept). */
  onReload?: () => void;
  /** True while that reload runs. */
  reloading?: boolean;
}

/**
 * Each default control as an invisible stand-in under a shimmer, so the
 * skeleton takes exactly the space the real control will, whatever
 * primitives the project registered.
 */
function GhostControl({ field }: { field?: FieldDef }): React.ReactElement {
  const kind = field?.kind ?? "string";
  let ghost: React.ReactElement;
  switch (kind) {
    case "text":
      ghost = <Textarea rows={4} disabled tabIndex={-1} />;
      break;
    case "json":
      ghost = <Textarea rows={5} disabled tabIndex={-1} className="font-mono" />;
      break;
    case "boolean":
      ghost = <Switch disabled tabIndex={-1} />;
      break;
    case "file":
      ghost = <FileUpload disabled />;
      break;
    default:
      ghost = <Input disabled tabIndex={-1} />;
  }
  return (
    <div className={cn("relative", kind === "boolean" ? "w-fit" : "w-full")}>
      <div className="invisible">{ghost}</div>
      <Skeleton
        className={cn("absolute inset-0", kind === "boolean" ? "rounded-full" : "rounded-md")}
      />
    </div>
  );
}

const PLACEHOLDER_ROWS = [0, 1, 2, 3];

/**
 * The loading state: the form's own layout with shimmering controls. Once the
 * schema is known it has the real field count, kinds, labels and help text,
 * and the submit row sits where the real one will, so nothing shifts when the
 * values arrive.
 */
export function ResourceFormSkeleton({
  fields,
  submitLabel,
  showSubmitRow,
}: ResourceFormLoadingProps): React.ReactElement {
  return (
    <div role="status" aria-label="Loading form" aria-busy="true" className="space-y-5">
      <div className="space-y-5" aria-hidden="true">
        {fields !== undefined
          ? fields.map((field) => (
              <div key={field.name} className={FIELD_GAP}>
                <Label>
                  {field.label}
                  {field.required && field.kind !== "boolean" ? (
                    <span className="text-destructive">{" *"}</span>
                  ) : null}
                </Label>
                <GhostControl field={field} />
                {field.description !== undefined ? (
                  <p className="text-sm text-muted-foreground">{field.description}</p>
                ) : null}
              </div>
            ))
          : PLACEHOLDER_ROWS.map((row) => (
              <div key={row} className={FIELD_GAP}>
                <Skeleton className={cn("h-3.5", row % 2 === 0 ? "w-24" : "w-32")} />
                <GhostControl />
              </div>
            ))}
      </div>
      {showSubmitRow ? (
        <div className={SUBMIT_ROW} aria-hidden="true">
          <div className="relative">
            <Button type="button" disabled tabIndex={-1} className="invisible">
              {submitLabel}
            </Button>
            <Skeleton className="absolute inset-0 rounded-md" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** The 403-on-load state: the role cannot edit this row, said plainly. */
export function ResourceFormForbidden({
  action,
  resource,
}: ResourceFormForbiddenProps): React.ReactElement {
  return <PermissionDenied action={action} resource={resource} />;
}

/** A failed load, with "Try again" when it can help. */
export function ResourceFormLoadError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState {...props} />;
}

/**
 * Every problem after a failed submit, at the top of the form, each field a
 * link that moves focus to it (links wrap like text, so a long message keeps
 * its bullet on its first line). Announced when it appears.
 */
export function ResourceFormErrorSummary({
  title,
  errors,
}: ResourceFormErrorSummaryProps): React.ReactElement {
  const titleId = React.useId();
  return (
    <div
      role="alert"
      aria-labelledby={titleId}
      className="rounded-md border border-destructive-border bg-destructive-subtle px-4 py-3 text-sm"
    >
      <p id={titleId} className="flex items-center gap-2 font-semibold text-foreground">
        <AlertIcon className="h-4 w-4 shrink-0 text-destructive" />
        {title}
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-10 text-foreground marker:text-destructive">
        {errors.map((entry, index) => (
          <li key={entry.name ?? `form-${index}`}>
            {entry.focus !== undefined ? (
              <a
                href={entry.href ?? "#"}
                onClick={(event) => {
                  event.preventDefault();
                  entry.focus?.();
                }}
                className="rounded-sm underline decoration-destructive underline-offset-4 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {entry.label}: {entry.message}
              </a>
            ) : (
              <span>{entry.message}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

const BANNER_ICONS: Partial<Record<KarniErrorKind, React.ComponentType<{ className?: string }>>> = {
  offline: OfflineIcon,
  network: OfflineIcon,
  forbidden: LockIcon,
  unauthenticated: LockIcon,
};

/**
 * A submit that failed for a reason other than the values (offline, the
 * server, permission, a conflict): a compact banner above the fields, in
 * describeError's plain words, with "Try again" when it can help and "Load
 * the latest version" after a conflict. The values the user typed stay in
 * the fields.
 */
export function ResourceFormSubmitError({
  error,
  context,
  onRetry,
  retrying = false,
  onReload,
  reloading = false,
}: ResourceFormSubmitErrorProps): React.ReactElement {
  const described = describeError(error, context);
  const Icon = BANNER_ICONS[described.kind] ?? AlertIcon;
  const retry = described.retryable && onRetry !== undefined;
  const reload = described.kind === "conflict" && onReload !== undefined;
  return (
    <div
      role="alert"
      data-error-kind={described.kind}
      className="flex gap-3 rounded-md border border-destructive-border bg-destructive-subtle px-4 py-3 text-sm"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-foreground">{described.title}</p>
        <p className="mt-1 text-muted-foreground">{described.description}</p>
        {described.detail !== undefined ? (
          <p className="mt-1 text-xs text-muted-foreground">{described.detail}</p>
        ) : null}
        {retry || reload ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {retry ? (
              <PendingButton
                variant="outline"
                size="sm"
                onClick={onRetry}
                pending={retrying}
                pendingLabel="Trying again…"
              >
                Try again
              </PendingButton>
            ) : null}
            {reload ? (
              <PendingButton
                variant="outline"
                size="sm"
                onClick={onReload}
                pending={reloading}
                pendingLabel="Loading the latest version…"
              >
                Load the latest version
              </PendingButton>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
