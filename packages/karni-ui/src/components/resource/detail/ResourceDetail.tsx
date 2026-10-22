import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { karniKeys } from "../../../hooks/keys";
import type { ResourceItemParams } from "../../../hooks/types";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import type { FieldDef } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { describeError } from "../../../states/describe-error";
import { ErrorState, type ErrorSlotProps } from "../../../states/ErrorState";
import { useDelayedFlag, useOnlineStatus } from "../../../states/hooks";
import { PendingButton } from "../../../states/PendingButton";
import { Modal, ModalClose } from "../../modal/modal";
import { Button } from "../../primitives/button";
import { CheckIcon, SearchIcon } from "../../primitives/icons";
import { Skeleton } from "../../primitives/skeleton";
import { partitionAuditFields } from "../audit-fields";
import { displayLabel } from "../displayLabel";
import { EmptyValue } from "../empty-value";
import { humanizeValue } from "../form/prepare";
import { singularNoun } from "../nouns";
import { offlineError, useRetryUnlessClientError, useRetryWhenOnline } from "../query-state";

registerComponentRole("detail-view", "ResourceDetail");

type Item = Record<string, unknown>;

export interface ResourceDetailFieldOverride {
  label?: string;
  hidden?: boolean;
  render?: (value: unknown, item: Record<string, unknown>) => React.ReactNode;
}

/** What the `Loading` slot receives. */
export interface ResourceDetailLoadingProps {
  /** The domain fields the record will show, in order. Undefined while the schema loads. */
  fields: readonly FieldDef[] | undefined;
  /** The audit fields of the "Record" group. Undefined while the schema loads. */
  auditFields: readonly FieldDef[] | undefined;
  /** True once loading has taken longer than SLOW_AFTER_MS (500ms): show the placeholder now. */
  slow: boolean;
}

/** What the `Error` slot receives: ErrorSlotProps plus the `back` prop. */
export interface ResourceDetailErrorProps extends ErrorSlotProps {
  /** The way out of the screen (the `back` prop). */
  back?: React.ReactNode;
}

/** What the `NotFound` slot receives (the backend answered 404). */
export interface ResourceDetailNotFoundProps {
  error: unknown;
  /** The resource in words, singular: "event". */
  resourceLabel: string;
  back?: React.ReactNode;
}

/** What the `Deleted` slot receives, after a delete from this view succeeded. */
export interface ResourceDetailDeletedProps {
  item: Item;
  resourceLabel: string;
  back?: React.ReactNode;
}

/** What the `EmptyValue` slot receives: a visible field with no value. */
export interface ResourceDetailEmptyValueProps {
  field: FieldDef;
}

/** What the `DeleteDialog` slot receives: the confirmation before a delete. */
export interface ResourceDetailDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  item: Item;
  /** displayLabel(item): "Launch party". */
  itemLabel: string;
  resourceLabel: string;
  onConfirm: () => void;
  /** True while the delete request runs. */
  pending: boolean;
  /** The failed attempt's error (null before an attempt and while one runs). */
  error: unknown;
}

/**
 * The replaceable parts of ResourceDetail. Pass any subset as `slots`.
 * `defaultResourceDetailSlots` holds Karni's own, to wrap them.
 */
export interface ResourceDetailSlots {
  /** The field placeholders while the record loads (the header is ResourceDetail's own). */
  Loading: React.ComponentType<ResourceDetailLoadingProps>;
  /** Any failure but a 404: offline, server error, 403, ... */
  Error: React.ComponentType<ResourceDetailErrorProps>;
  /** The backend answered 404: the record does not exist or is outside the user's scope. */
  NotFound: React.ComponentType<ResourceDetailNotFoundProps>;
  /** A visible field whose value is empty. */
  EmptyValue: React.ComponentType<ResourceDetailEmptyValueProps>;
  /** The delete confirmation. */
  DeleteDialog: React.ComponentType<ResourceDetailDeleteDialogProps>;
  /** Shown in place of the record once it is deleted from this view. */
  Deleted: React.ComponentType<ResourceDetailDeletedProps>;
}

export interface ResourceDetailProps {
  resource: string;
  id: string | number;
  fields?: Record<string, ResourceDetailFieldOverride>;
  /** Appended below the field list (e.g. a child <ResourceTable>), even while the record loads. */
  sections?: ReadonlyArray<React.ReactNode>;
  expand?: readonly string[];
  /** The heading. A function receives the loaded record. A placeholder stands in until then. */
  title?: React.ReactNode | ((item: Item) => React.ReactNode);
  /** Shown in the header next to Edit and Delete. A function receives the loaded record. */
  actions?: React.ReactNode | ((item: Item) => React.ReactNode);
  /** The resource in words, singular, for messages ("Couldn't find this event"). Default: from `resource`. */
  resourceLabel?: string;
  /** A way back (a link or button to the list), shown when the record is missing, fails or is deleted. */
  back?: React.ReactNode;
  /** Shows an Edit button that calls this with the record. */
  onEdit?: (item: Item) => void;
  /** Whether the user may edit this record (the role, the record's state). Default true. */
  canEdit?: boolean | ((item: Item) => boolean);
  /** Shows a Delete button, which asks for confirmation first. */
  enableDelete?: boolean;
  /** Whether the user may delete this record. Default true. */
  canDelete?: boolean | ((item: Item) => boolean);
  /** Called after a confirmed delete succeeded (navigate away from here). */
  onDeleted?: (item: Item) => void;
  /** Replace parts of the view: Loading, Error, NotFound, EmptyValue, DeleteDialog, Deleted. */
  slots?: Partial<ResourceDetailSlots>;
  className?: string;
}

function fileBasename(url: string): string {
  const withoutQuery = url.split(/[?#]/, 1)[0] ?? url;
  const segments = withoutQuery.split("/").filter((segment) => segment !== "");
  return segments[segments.length - 1] ?? url;
}

function formatDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (match !== null) {
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return date.toLocaleDateString();
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function RelationEntry({ value }: { value: unknown }): React.ReactElement {
  if (value !== null && typeof value === "object") {
    return <>{displayLabel(value as Record<string, unknown>)}</>;
  }
  return <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{String(value)}</code>;
}

function RelationValue({ value }: { value: unknown }): React.ReactElement {
  if (Array.isArray(value)) {
    return (
      <span className="flex flex-wrap gap-1.5">
        {value.map((entry, index) => (
          <span
            key={index}
            className="inline-flex items-center rounded-sm bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground"
          >
            <RelationEntry value={entry} />
          </span>
        ))}
      </span>
    );
  }
  return <RelationEntry value={value} />;
}

function isEmpty(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

/** Default value renderer per field kind, overridable per field via `fields`. */
function DefaultValue(props: {
  field: FieldDef;
  value: unknown;
  Empty: React.ComponentType<ResourceDetailEmptyValueProps>;
}): React.ReactElement {
  const { field, value, Empty } = props;
  if (isEmpty(value)) return <Empty field={field} />;
  switch (field.kind) {
    case "boolean":
      return <>{value ? "Yes" : "No"}</>;
    case "date":
      return <>{formatDate(String(value))}</>;
    case "datetime":
      return <>{formatDateTime(String(value))}</>;
    case "enum":
      return <>{field.enumLabels?.[String(value)] ?? humanizeValue(String(value))}</>;
    case "relation":
      return <RelationValue value={value} />;
    case "file":
      return (
        <a
          href={String(value)}
          target="_blank"
          rel="noreferrer"
          className="rounded-sm font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          {fileBasename(String(value))}
        </a>
      );
    case "json":
      return (
        <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(value, null, 2)}
        </pre>
      );
    case "number":
    case "integer":
      return <>{typeof value === "number" ? value.toLocaleString() : String(value)}</>;
    case "array":
      return <>{Array.isArray(value) ? value.map(String).join(", ") : String(value)}</>;
    default:
      return <>{String(value)}</>;
  }
}

function DefaultEmptyValue(): React.ReactElement {
  return <EmptyValue />;
}

// loading

/** Rows drawn before the schema has loaded (it usually is: the schema is fetched once per app). */
const PLACEHOLDER_ROWS = 5;
const VALUE_WIDTHS = ["w-48", "w-64", "w-32", "w-56", "w-40"] as const;

function valueWidth(field: FieldDef | undefined, index: number): string {
  switch (field?.kind) {
    case "boolean":
      return "w-10";
    case "number":
    case "integer":
      return "w-16";
    case "date":
      return "w-24";
    case "datetime":
      return "w-40";
    default:
      return VALUE_WIDTHS[index % VALUE_WIDTHS.length] ?? "w-48";
  }
}

/** One placeholder row, the same height as a DetailRow with one line of text. */
function RowPlaceholder(props: {
  field: FieldDef | undefined;
  index: number;
  muted: boolean;
}): React.ReactElement {
  const { field, index, muted } = props;
  const bar = muted ? "my-0.5 h-3" : "my-0.5 h-4";
  return (
    <div className={cn("grid grid-cols-1 gap-1 sm:grid-cols-3 sm:gap-4", muted ? "py-2" : "py-3")}>
      <div>
        <Skeleton className={cn(bar, muted ? "w-20" : "w-24")} />
      </div>
      <div className="sm:col-span-2">
        {field?.kind === "json" && !muted ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <Skeleton className={cn(bar, valueWidth(field, index))} />
        )}
      </div>
    </div>
  );
}

/**
 * The default `Loading` slot: the record's own layout (one row per field the
 * schema declares, then the "Record" group), drawn only once loading is
 * slow so a fast load never flashes it. The space is held from the start.
 */
function DefaultLoading({
  fields,
  auditFields,
  slow,
}: ResourceDetailLoadingProps): React.ReactElement {
  const domain: ReadonlyArray<FieldDef | undefined> =
    fields ?? Array.from({ length: PLACEHOLDER_ROWS }, () => undefined);
  return (
    <div
      className={cn("space-y-6", !slow && "invisible")}
      aria-hidden="true"
      data-testid="resource-detail-skeleton"
    >
      <div className="[&>*+*]:border-t [&>*+*]:border-border">
        {domain.map((field, index) => (
          <RowPlaceholder key={field?.name ?? index} field={field} index={index} muted={false} />
        ))}
      </div>
      {auditFields !== undefined && auditFields.length > 0 ? (
        <div className="rounded-md border border-border bg-muted-subtle px-4 py-2">
          <div className="py-1">
            <Skeleton className="my-0.5 h-3 w-14" />
          </div>
          <div className="[&>*+*]:border-t [&>*+*]:border-border">
            {auditFields.map((field, index) => (
              <RowPlaceholder key={field.name} field={field} index={index} muted />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// unhappy states

function DefaultError({ back, ...props }: ResourceDetailErrorProps): React.ReactElement {
  return <ErrorState {...props} actions={back} />;
}

const QUIET_PANEL =
  "flex w-full flex-col items-center gap-2 rounded-lg border border-border bg-muted-subtle px-6 py-8 text-center";

/**
 * A 404. Karni answers 404 both for a record that does not exist and for one
 * outside the user's scope, so the words never say it exists.
 */
function DefaultNotFound({ resourceLabel, back }: ResourceDetailNotFoundProps): React.ReactElement {
  return (
    <div role="alert" data-error-kind="not-found" className={QUIET_PANEL}>
      <SearchIcon className="mb-1 h-8 w-8 text-muted-foreground" />
      <p className="text-base font-semibold text-foreground">
        Couldn&apos;t find this {resourceLabel}
      </p>
      <p className="max-w-128 text-sm text-muted-foreground">
        The link may be wrong, or the {resourceLabel} may have been deleted or not shared with you.
      </p>
      {back !== undefined && back !== null ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">{back}</div>
      ) : null}
    </div>
  );
}

function DefaultDeleted({ resourceLabel, back }: ResourceDetailDeletedProps): React.ReactElement {
  return (
    <div className={QUIET_PANEL}>
      <CheckIcon className="mb-1 h-8 w-8 text-muted-foreground" />
      <p className="text-base font-semibold text-foreground">The {resourceLabel} was deleted</p>
      {back !== undefined && back !== null ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">{back}</div>
      ) : null}
    </div>
  );
}

function DefaultDeleteDialog(props: ResourceDetailDeleteDialogProps): React.ReactElement {
  const { open, onOpenChange, itemLabel, resourceLabel, onConfirm, pending, error } = props;
  const errorRef = React.useRef<HTMLDivElement>(null);
  const failed = error !== null && error !== undefined;
  // A failed delete moves focus to what went wrong (the button it was on is disabled meanwhile).
  React.useEffect(() => {
    if (failed) errorRef.current?.focus();
  }, [failed, error]);
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete this ${resourceLabel}?`}
      description={
        <>
          <span className="font-medium text-foreground">{itemLabel}</span> will be deleted. This
          can&apos;t be undone.
        </>
      }
      footer={
        <>
          <ModalClose asChild>
            <Button variant="outline" disabled={pending}>
              Cancel
            </Button>
          </ModalClose>
          <PendingButton
            variant="destructive"
            pending={pending}
            pendingLabel="Deleting…"
            onClick={onConfirm}
          >
            Delete
          </PendingButton>
        </>
      }
    >
      {failed ? (
        <ErrorState
          ref={errorRef}
          tabIndex={-1}
          variant="inline"
          className="rounded-md border border-destructive-border bg-destructive-subtle p-3 focus:outline-none"
          error={error}
          context={{ action: "delete", resource: `this ${resourceLabel}` }}
        />
      ) : null}
    </Modal>
  );
}

/** Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultResourceDetailSlots: ResourceDetailSlots = {
  Loading: DefaultLoading,
  Error: DefaultError,
  NotFound: DefaultNotFound,
  EmptyValue: DefaultEmptyValue,
  DeleteDialog: DefaultDeleteDialog,
  Deleted: DefaultDeleted,
};

function DetailRow(props: {
  field: FieldDef;
  item: Record<string, unknown>;
  override: ResourceDetailFieldOverride | undefined;
  muted: boolean;
  Empty: React.ComponentType<ResourceDetailEmptyValueProps>;
}): React.ReactElement {
  const { field, item, override, muted, Empty } = props;
  const value = item[field.name];
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-1 sm:grid-cols-3 sm:gap-4",
        muted ? "py-2 text-xs" : "py-3 text-sm",
      )}
    >
      <dt className="font-medium text-muted-foreground">{override?.label ?? field.label}</dt>
      <dd className={cn("sm:col-span-2", muted ? "text-muted-foreground" : "text-foreground")}>
        {override?.render !== undefined ? (
          override.render(value, item)
        ) : (
          <DefaultValue field={field} value={value} Empty={Empty} />
        )}
      </dd>
    </div>
  );
}

function allowed(rule: boolean | ((item: Item) => boolean) | undefined, item: Item): boolean {
  if (rule === undefined) return true;
  return typeof rule === "function" ? rule(item) : rule;
}

/** The fields a row shows: readable, known, not hidden by an override, and present in the payload. */
function shownFields(
  fields: readonly FieldDef[],
  overrides: Record<string, ResourceDetailFieldOverride> | undefined,
  item: Item | undefined,
): readonly FieldDef[] {
  return fields.filter(
    (field) =>
      !field.writeOnly &&
      field.kind !== "unknown" &&
      overrides?.[field.name]?.hidden !== true &&
      // A field the role may not read is absent from the payload: no row, no dash, no hint.
      (item === undefined || field.name in item),
  );
}

/**
 * Schema-driven read view of one row: every readable field, labelled and formatted.
 *
 * Contract "ResourceDetail": a definition list of every non-writeOnly field
 * the payload carries, with domain fields first (schema order), then the audit
 * fields (AUDIT_FIELDS: id, created_at, updated_at, created_by, updated_by)
 * in a visually muted "Record" group. A field the role may not read
 * (`Karni.field_roles`) is absent from the per-role schema and the payload,
 * so it has no row at all. A visible field with no value shows EmptyValue
 * (a dash, read as "empty"). Relations render through displayLabel when the
 * object is expanded (the field is in `expand`), else as the raw id in <code>.
 *
 * States: a placeholder in the record's own layout while it loads (drawn
 * after 500ms, the header in place from the start). A 404 shows "Couldn't
 * find this <resource>", and Karni also answers 404 for a record outside the
 * user's scope. Everything else shows describeError's words, with "Try again"
 * when it can help (it refetches the schema too when that failed). Offline
 * says so and reloads when the connection returns.
 *
 * Escape hatches: per-field `fields` overrides (label/hidden/render, audit
 * fields included), appended `sections`, the title/actions header, the
 * `canEdit`/`canDelete` predicates, and `slots` for every state.
 */
export function ResourceDetail(props: ResourceDetailProps): React.ReactElement {
  const {
    resource,
    id,
    fields,
    sections,
    expand,
    title,
    actions,
    resourceLabel,
    back,
    onEdit,
    canEdit,
    enableDelete = false,
    canDelete,
    onDeleted,
    slots,
    className,
  } = props;
  const Slots: ResourceDetailSlots = { ...defaultResourceDetailSlots, ...slots };
  const label = resourceLabel ?? singularNoun(resource);
  const recordHeadingId = React.useId();
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const retry = useRetryUnlessClientError();

  const schemaResult = useSchema(resource);
  const schemaFetching = useIsFetching({ queryKey: karniKeys.schema() }) > 0;
  const { remove } = useResourceMutations(resource);
  const params: ResourceItemParams | undefined = React.useMemo(
    () => (expand !== undefined && expand.length > 0 ? { expand } : undefined),
    [expand],
  );
  const itemQuery = useResourceItem(resource, id, params, {
    retry,
    // Once deleted here, the record is gone: do not ask for it again.
    enabled: !remove.isSuccess,
  });

  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const deletedRef = React.useRef<HTMLDivElement>(null);
  const deletedItem = remove.isSuccess ? itemQuery.data : undefined;
  const deleted = deletedItem !== undefined;
  React.useEffect(() => {
    if (deleted) deletedRef.current?.focus();
  }, [deleted]);
  // Closing the confirmation without deleting returns focus to the Delete
  // button (the dialog has no Radix trigger of its own to return it to).
  const deleteButtonRef = React.useRef<HTMLButtonElement>(null);
  const wasOpen = React.useRef(false);
  React.useEffect(() => {
    const closed = wasOpen.current && !deleteOpen;
    wasOpen.current = deleteOpen;
    if (!closed || remove.isSuccess) return undefined;
    const timer = setTimeout(() => deleteButtonRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [deleteOpen, remove.isSuccess]);

  const schema = schemaResult.data;
  const item = itemQuery.data;
  const schemaError = schema === undefined ? schemaResult.error : undefined;
  const itemError = itemQuery.error;
  // While a delete runs, the resource is refetched and this record 404s: that is the delete, not an error.
  const deleting = remove.isPending || remove.isSuccess;
  const blockingItemError =
    !deleting &&
    itemError !== null &&
    itemError !== undefined &&
    (item === undefined || !describeError(itemError).retryable);
  const error = schemaError != null ? schemaError : blockingItemError ? itemError : undefined;
  const loading = schema === undefined || item === undefined;
  const offline = error === undefined && loading && (!online || itemQuery.fetchStatus === "paused");
  const slow = useDelayedFlag(loading && error === undefined && !offline);

  const retryAll = React.useCallback((): void => {
    if (schemaResult.error != null && schemaResult.data === undefined) {
      void queryClient.refetchQueries({ queryKey: karniKeys.schema() });
    }
    if (itemQuery.error != null || itemQuery.data === undefined) void itemQuery.refetch();
  }, [queryClient, schemaResult.error, schemaResult.data, itemQuery]);
  useRetryWhenOnline(error, retryAll);
  const retrying = itemQuery.isFetching || schemaFetching;

  if (deletedItem !== undefined) {
    return (
      <div
        ref={deletedRef}
        tabIndex={-1}
        role="status"
        className={cn("focus:outline-none", className)}
      >
        <Slots.Deleted item={deletedItem} resourceLabel={label} back={back} />
      </div>
    );
  }

  if (error !== undefined) {
    if (error === itemError && describeError(error).kind === "not-found") {
      return (
        <div className={className}>
          <Slots.NotFound error={error} resourceLabel={label} back={back} />
        </div>
      );
    }
    return (
      <div className={className}>
        <Slots.Error
          error={error}
          context={{ action: "view", resource: `this ${label}` }}
          onRetry={retryAll}
          retrying={retrying}
          back={back}
        />
      </div>
    );
  }

  if (offline) {
    return (
      <div className={className}>
        <Slots.Error
          error={offlineError()}
          context={{ action: "view", resource: `this ${label}` }}
          onRetry={retryAll}
          retrying={false}
          back={back}
        />
      </div>
    );
  }

  const domainAndAudit =
    schema !== undefined
      ? partitionAuditFields(shownFields(schema.fields, fields, item))
      : undefined;
  const mayEdit = onEdit !== undefined && canEdit !== false;
  const mayDelete = enableDelete && canDelete !== false;
  const hasHeader = title !== undefined || actions !== undefined || mayEdit || mayDelete;

  const header = hasHeader ? (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {title === undefined ? (
        <div />
      ) : typeof title === "function" ? (
        item === undefined ? (
          <div className="py-1">
            {/* Narrow enough on a phone to share the line with the buttons, as a short title does. */}
            <Skeleton className={cn("h-5 w-32 sm:w-48", !slow && "invisible")} />
          </div>
        ) : (
          <h2 className="text-lg font-semibold tracking-tight">{title(item)}</h2>
        )
      ) : (
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      )}
      {actions !== undefined || mayEdit || mayDelete ? (
        <div className="flex flex-wrap items-center gap-2">
          {item === undefined ? (
            <>
              {typeof actions === "function" ? (
                <Skeleton className={cn("h-10 w-24", !slow && "invisible")} />
              ) : (
                actions
              )}
              {mayEdit ? <Skeleton className={cn("h-10 w-16", !slow && "invisible")} /> : null}
              {mayDelete ? <Skeleton className={cn("h-10 w-20", !slow && "invisible")} /> : null}
            </>
          ) : (
            <>
              {typeof actions === "function" ? actions(item) : actions}
              {onEdit !== undefined && mayEdit && allowed(canEdit, item) ? (
                <Button variant="outline" onClick={() => onEdit(item)}>
                  Edit
                </Button>
              ) : null}
              {mayDelete && allowed(canDelete, item) ? (
                <Button
                  ref={deleteButtonRef}
                  variant="outline"
                  onClick={() => {
                    remove.reset();
                    setDeleteOpen(true);
                  }}
                >
                  Delete
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  ) : null;

  const appended =
    sections !== undefined && sections.length > 0 ? (
      <div className="space-y-6">
        {sections.map((section, index) => (
          <div key={index}>{section}</div>
        ))}
      </div>
    ) : null;

  if (item === undefined || domainAndAudit === undefined) {
    const placeholder =
      schema !== undefined
        ? partitionAuditFields(shownFields(schema.fields, fields, undefined))
        : undefined;
    return (
      <div className={cn("space-y-6", className)} aria-busy="true">
        <span role="status" aria-label="Loading details" className="sr-only">
          {slow ? `Loading this ${label}…` : ""}
        </span>
        {header}
        <Slots.Loading fields={placeholder?.domain} auditFields={placeholder?.audit} slow={slow} />
        {appended}
      </div>
    );
  }

  const { domain, audit } = domainAndAudit;
  return (
    <div className={cn("space-y-6", className)}>
      {header}
      <dl className="[&>*+*]:border-t [&>*+*]:border-border">
        {domain.map((field) => (
          <DetailRow
            key={field.name}
            field={field}
            item={item}
            override={fields?.[field.name]}
            muted={false}
            Empty={Slots.EmptyValue}
          />
        ))}
      </dl>
      {audit.length > 0 ? (
        <section
          aria-labelledby={recordHeadingId}
          className="rounded-md border border-border bg-muted-subtle px-4 py-2"
        >
          <h3
            id={recordHeadingId}
            className="py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Record
          </h3>
          <dl className="[&>*+*]:border-t [&>*+*]:border-border">
            {audit.map((field) => (
              <DetailRow
                key={field.name}
                field={field}
                item={item}
                override={fields?.[field.name]}
                muted
                Empty={Slots.EmptyValue}
              />
            ))}
          </dl>
        </section>
      ) : null}
      {appended}
      {mayDelete ? (
        <Slots.DeleteDialog
          open={deleteOpen}
          onOpenChange={(open) => {
            if (!remove.isPending) setDeleteOpen(open);
          }}
          item={item}
          itemLabel={displayLabel(item)}
          resourceLabel={label}
          pending={remove.isPending}
          error={remove.error}
          onConfirm={() =>
            remove.mutate(id, {
              onSuccess: () => {
                setDeleteOpen(false);
                onDeleted?.(item);
              },
            })
          }
        />
      ) : null}
    </div>
  );
}
