import * as React from "react";
import {
  downloadImportTemplate,
  isImportInFlight,
  useImportActions,
  useImportDescribe,
  useImportJob,
  type ImportColumn,
  type ImportJob,
  type ImportProblem,
  type ImportResult,
} from "../../../hooks/useResourceImport";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { KarniApiError } from "../../../schema/client";
import { useKarniClient } from "../../../schema/provider";
import { describeError } from "../../../states/describe-error";
import { ErrorState, type ErrorSlotProps } from "../../../states/ErrorState";
import { useDelayedFlag, useOnlineStatus } from "../../../states/hooks";
import { PendingButton } from "../../../states/PendingButton";
import { Modal, ModalClose } from "../../modal/modal";
import { Button } from "../../primitives/button";
import { AlertIcon, LockIcon, OfflineIcon } from "../../primitives/icons";
import { Input } from "../../primitives/input";
import { Label } from "../../primitives/label";
import { Select } from "../../primitives/select";
import { Skeleton } from "../../primitives/skeleton";
import { EmptyValue } from "../empty-value";
import { pluralNoun } from "../nouns";
import { offlineError, useRetryUnlessClientError, useRetryWhenOnline } from "../query-state";

registerComponentRole("resource-import", "ResourceImport");

/** What the `Loading` slot receives while the import description loads. */
export interface ResourceImportLoadingProps {
  /** True once loading has taken longer than SLOW_AFTER_MS (500ms): show the placeholder now. */
  slow: boolean;
}

/** What the `Progress` slot receives while the backend previews or commits a job. */
export interface ImportProgressProps {
  job: ImportJob;
}

/** What the `Summary` slot receives: a preview's or a commit's counts. */
export interface ImportSummaryProps {
  job: ImportJob;
  result: ImportResult;
}

/** What the `Problems` slot receives: the rows the backend refused, with why. */
export interface ImportProblemsProps {
  job: ImportJob;
  problems: readonly ImportProblem[];
}

/** What the `ConfirmCommit` slot receives: the step between a preview and its commit. */
export interface ImportConfirmProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  job: ImportJob;
  /** The preview's counts: what the commit will do. */
  result: ImportResult;
  /** The resource in words, plural: "events". */
  resourceLabel: string;
  onConfirm: () => void;
  /** True while the commit request runs. */
  pending: boolean;
  /** Why the last commit attempt failed (null before an attempt and while one runs). */
  error: unknown;
}

/**
 * The replaceable parts of ResourceImport. Pass any subset as `slots`.
 * `defaultResourceImportSlots` holds Karni's own, to wrap them.
 */
export interface ResourceImportSlots {
  /** The upload form's placeholder while the import description loads. */
  Loading: React.ComponentType<ResourceImportLoadingProps>;
  /** A failure: loading what the import accepts, an upload, a preview. */
  Error: React.ComponentType<ErrorSlotProps>;
  /** A running preview or commit. */
  Progress: React.ComponentType<ImportProgressProps>;
  /** Created / updated / skipped counts. */
  Summary: React.ComponentType<ImportSummaryProps>;
  /** The table of rows with errors. */
  Problems: React.ComponentType<ImportProblemsProps>;
  /** The confirmation before a commit. */
  ConfirmCommit: React.ComponentType<ImportConfirmProps>;
}

export interface ResourceImportProps {
  resource: string;
  title?: React.ReactNode;
  /** Called when a commit finishes (the job is `done`). */
  onDone?: (job: ImportJob) => void;
  /** The resource in words, plural, for messages ("You can't import events"). Default: from `resource`. */
  resourceLabel?: string;
  /** Replace parts of the flow: Loading, Error, Progress, Summary, Problems, ConfirmCommit. */
  slots?: Partial<ResourceImportSlots>;
  className?: string;
}

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

/** The backend's own explanation of a refused file or mapping (a KarniValueError or a field error). */
function refusal(error: unknown): string | undefined {
  if (!(error instanceof KarniApiError) || typeof error.data !== "object" || error.data === null) {
    return undefined;
  }
  const data = error.data as Record<string, unknown>;
  if (typeof data["detail"] === "string") return data["detail"];
  for (const value of Object.values(data)) {
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  }
  return undefined;
}

const VALIDATION_TITLES: Record<string, string> = {
  upload: "This file can't be imported",
  preview: "This mapping can't be previewed",
  commit: "This import can't be committed",
};

const ERROR_ICONS: Partial<Record<string, React.ComponentType<{ className?: string }>>> = {
  forbidden: LockIcon,
  offline: OfflineIcon,
  network: OfflineIcon,
};

/**
 * The default `Error` slot. When loading what the import accepts fails, the
 * whole step is ErrorState's panel. A failed upload or preview is a compact
 * alert under the form it came from, and a refused file or mapping (a 400)
 * says what the backend objected to.
 */
function DefaultImportError(props: ErrorSlotProps): React.ReactElement {
  const { error, context, onRetry, retrying = false } = props;
  if (context?.action === "import") return <ErrorState {...props} />;
  const described = describeError(error, context);
  const refused = described.kind === "validation";
  const Icon = ERROR_ICONS[described.kind] ?? AlertIcon;
  return (
    <div
      role="alert"
      data-error-kind={described.kind}
      className="flex items-start gap-2 rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium text-foreground">
          {refused
            ? (VALIDATION_TITLES[context?.action ?? ""] ?? "This can't be imported")
            : described.title}
        </p>
        <p className="text-muted-foreground">
          {refused
            ? (refusal(error) ?? "Check the file against the template, then try again.")
            : described.description}
        </p>
        {!refused && described.detail !== undefined ? (
          <p className="text-xs text-muted-foreground">{described.detail}</p>
        ) : null}
        {described.retryable && onRetry !== undefined ? (
          <div className="pt-2">
            <PendingButton
              variant="outline"
              size="sm"
              onClick={onRetry}
              pending={retrying}
              pendingLabel="Trying again…"
            >
              Try again
            </PendingButton>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function DefaultImportLoading({ slow }: ResourceImportLoadingProps): React.ReactElement {
  return (
    <div
      className={cn("space-y-3", !slow && "invisible")}
      aria-hidden="true"
      data-testid="resource-import-loading"
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid w-full max-w-96 gap-1.5">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
        <Skeleton className="h-10 w-20" />
      </div>
      {/* The hint: one line, two on a phone. */}
      <div className="space-y-1">
        <Skeleton className="my-0.5 h-3 w-96 max-w-full" />
        <Skeleton className="my-0.5 h-3 w-40 sm:hidden" />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }): React.ReactElement {
  return (
    <div>
      <dt className="text-xs uppercase text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function DefaultSummary({ result }: ImportSummaryProps): React.ReactElement {
  const { created, updated, skipped, unchanged, errors } = result;
  return (
    <dl className="flex flex-wrap gap-6" data-testid="import-stats">
      <Stat label="Created" value={created} />
      <Stat label="Updated" value={updated} />
      <Stat
        label="Skipped"
        value={
          <>
            {skipped}{" "}
            <span className="text-sm font-normal text-muted-foreground">
              ({unchanged} unchanged, {errors} with errors)
            </span>
          </>
        }
      />
    </dl>
  );
}

function DefaultProblems({ problems }: ImportProblemsProps): React.ReactElement {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <caption className="px-3 py-2 text-left text-sm font-medium text-foreground">
          Rows with errors
        </caption>
        <thead className="bg-muted text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">
              Row
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Field
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Problem
            </th>
          </tr>
        </thead>
        <tbody>
          {problems.map((problem, index) => (
            <tr key={`${problem.row}-${problem.field}-${index}`} className="border-t border-border">
              <th scope="row" className="px-3 py-2 text-left font-normal tabular-nums">
                {problem.row}
              </th>
              <td className="px-3 py-2 font-mono text-xs">
                {problem.field || <EmptyValue label="the whole row" />}
              </td>
              <td className="px-3 py-2">{problem.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A running preview or commit. The bar is a `progressbar`. The polite
 * announcement changes only at each quarter, so a screen reader is not
 * read every poll (1.5s).
 */
function DefaultProgress({ job }: ImportProgressProps): React.ReactElement {
  const percent = job.rows_total > 0 ? Math.round((job.rows_done * 100) / job.rows_total) : 0;
  const verb = job.status === "previewing" ? "Previewing" : "Committing";
  const quarter = Math.min(100, Math.floor(percent / 25) * 25);
  return (
    <div className="space-y-2">
      <p className="text-sm tabular-nums">
        {verb}… {job.rows_done.toLocaleString()} / {job.rows_total.toLocaleString()} rows
      </p>
      <div
        role="progressbar"
        aria-label={`${verb} ${job.file_name}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${job.rows_done} of ${job.rows_total} rows`}
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
      </div>
      <span role="status" className="sr-only">
        {`${verb} ${plural(job.rows_total, "row", "rows")}: ${quarter}% done.`}
      </span>
    </div>
  );
}

function DefaultConfirmCommit(props: ImportConfirmProps): React.ReactElement {
  const { open, onOpenChange, job, result, resourceLabel, onConfirm, pending, error } = props;
  const errorRef = React.useRef<HTMLDivElement>(null);
  const failed = error !== null && error !== undefined;
  React.useEffect(() => {
    if (failed) errorRef.current?.focus();
  }, [failed, error]);
  const saved = result.created + result.updated;
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Commit this import?"
      description={`${job.file_name}: ${plural(saved, "row", "rows")} will be saved to ${resourceLabel}.`}
      footer={
        <>
          <ModalClose asChild>
            <Button variant="outline" disabled={pending}>
              Cancel
            </Button>
          </ModalClose>
          <PendingButton pending={pending} pendingLabel="Committing…" onClick={onConfirm}>
            Commit import
          </PendingButton>
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="import-confirm-counts">
        <Stat label="Created" value={result.created} />
        <Stat label="Updated" value={result.updated} />
        <Stat label="Unchanged" value={result.unchanged} />
        <Stat label="Failed" value={result.errors} />
      </dl>
      {result.errors > 0 ? (
        <p className="text-sm text-muted-foreground">
          {plural(result.errors, "row has", "rows have")} errors and will not be imported. Fix them
          in the file and import it again.
        </p>
      ) : null}
      {failed ? (
        <div ref={errorRef} tabIndex={-1} className="focus:outline-none">
          <ErrorState
            variant="inline"
            className="rounded-md border border-destructive-border bg-destructive-subtle p-3"
            error={error}
            context={{ action: "import", resource: resourceLabel }}
          />
        </div>
      ) : null}
    </Modal>
  );
}

/** Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultResourceImportSlots: ResourceImportSlots = {
  Loading: DefaultImportLoading,
  Error: DefaultImportError,
  Progress: DefaultProgress,
  Summary: DefaultSummary,
  Problems: DefaultProblems,
  ConfirmCommit: DefaultConfirmCommit,
};

function MappingTable(props: {
  job: ImportJob;
  fields: readonly ImportColumn[];
  mapping: Record<string, string>;
  onChange: (header: string, field: string) => void;
}): React.ReactElement {
  const { job, fields, mapping, onChange } = props;
  const options = fields.map((field) => ({
    value: field.name,
    label: `${field.name}${field.required ? " *" : ""}${field.key ? " (key)" : ""}`,
  }));
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <caption className="sr-only">Column mapping</caption>
        <thead className="bg-muted text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">
              Column in the file
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Field
            </th>
          </tr>
        </thead>
        <tbody>
          {job.columns.map((header) => (
            <tr key={header} className="border-t border-border">
              <th scope="row" className="px-3 py-2 text-left font-normal">
                {header}
              </th>
              <td className="px-3 py-2">
                <Select
                  aria-label={`Field for ${header}`}
                  className="h-9 w-auto min-w-48"
                  value={mapping[header] ?? ""}
                  options={options}
                  clearable
                  clearLabel="Ignore this column"
                  onValueChange={(next) => onChange(header, next ?? "")}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A request TanStack holds back while the browser is offline: it is sent when the connection returns. */
function WaitingForConnection({ what }: { what: string }): React.ReactElement {
  return (
    <p role="status" className="text-sm text-muted-foreground">
      You&apos;re offline. The {what} will be sent when you&apos;re back online.
    </p>
  );
}

type Step = "upload" | "map" | "progress" | "previewed" | "done";

function stepOf(job: ImportJob | undefined, remap: boolean): Step {
  if (job === undefined) return "upload";
  if (isImportInFlight(job)) return "progress";
  if (job.status === "uploaded" || job.status === "failed" || remap) return "map";
  return job.status === "done" ? "done" : "previewed";
}

/**
 * Import a CSV or XLSX file into a resource: upload, map columns to fields,
 * preview (the mandatory dry run, which shows N created / updated / skipped
 * with every row's errors), confirm, then commit. Drives
 * `/<resource>/import/…`. The backend validates every row through the same
 * serializer the API uses, keeps rows inside the user's scope and refuses
 * fields the role may not write. Large files run in the background with
 * progress.
 *
 * States: a placeholder in the form's layout while the import description
 * loads (drawn after 500ms). When that fails the form is not shown: a 403
 * reads "You can't import <resource>". A failed upload keeps the chosen file,
 * offers "Try again" when it can help and moves focus to the error. Offline
 * requests wait for the connection and say so. Escape hatch: `slots`.
 */
export function ResourceImport({
  resource,
  title = "Import",
  onDone,
  resourceLabel,
  slots,
  className,
}: ResourceImportProps): React.ReactElement {
  const Slots: ResourceImportSlots = { ...defaultResourceImportSlots, ...slots };
  const label = resourceLabel ?? pluralNoun(resource);
  const client = useKarniClient();
  const retry = useRetryUnlessClientError();
  const online = useOnlineStatus();
  const describe = useImportDescribe(resource, { retry });
  const actions = useImportActions(resource);
  const [jobId, setJobId] = React.useState<string | undefined>(undefined);
  const [mapping, setMapping] = React.useState<Record<string, string>>({});
  const [remap, setRemap] = React.useState(false);
  const [file, setFile] = React.useState<File | null>(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [templateError, setTemplateError] = React.useState<unknown>(null);
  const fileId = React.useId();
  const hintId = React.useId();
  const uploadErrorRef = React.useRef<HTMLDivElement>(null);
  const stepRef = React.useRef<HTMLDivElement>(null);
  const jobQuery = useImportJob(resource, jobId);
  const job = jobQuery.data;

  // The job's mapping (suggested or remembered) seeds the editable one.
  const seededFor = React.useRef<string | undefined>(undefined);
  React.useEffect(() => {
    if (job !== undefined && seededFor.current !== job.id) {
      seededFor.current = job.id;
      setMapping(job.mapping);
    }
  }, [job]);

  React.useEffect(() => {
    if (job?.status === "done") onDone?.(job);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fire once per completion
  }, [job?.status, job?.id]);

  const { upload, preview, commit } = actions;
  const busy = upload.isPending || preview.isPending || commit.isPending;
  const step = stepOf(job, remap);

  // Each step that replaces the one the user acted on takes the focus, so
  // keyboard and screen reader users land on what happened. The timer runs
  // after a closing dialog has restored focus to its (now gone) trigger.
  const shownStep = React.useRef(step);
  React.useEffect(() => {
    if (shownStep.current === step) return undefined;
    shownStep.current = step;
    const timer = setTimeout(() => stepRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [step]);

  // Cancelling the confirmation returns focus to Commit (the dialog has no
  // Radix trigger of its own to return it to); a commit moves on to its step.
  const commitButtonRef = React.useRef<HTMLButtonElement>(null);
  const wasConfirming = React.useRef(false);
  React.useEffect(() => {
    const closed = wasConfirming.current && !confirmOpen;
    wasConfirming.current = confirmOpen;
    if (!closed) return undefined;
    const timer = setTimeout(() => commitButtonRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [confirmOpen]);

  // A failed upload moves focus to what went wrong; the chosen file stays.
  React.useEffect(() => {
    if (upload.error !== null && upload.error !== undefined) uploadErrorRef.current?.focus();
  }, [upload.error]);

  const describeLoading = describe.data === undefined && describe.isPending;
  const describeOffline =
    describe.data === undefined &&
    describe.error == null &&
    (!online || describe.fetchStatus === "paused");
  const loadError = describe.data === undefined ? describe.error : null;
  const slow = useDelayedFlag(describeLoading && !describeOffline);
  const retryDescribe = React.useCallback((): void => {
    void describe.refetch();
  }, [describe]);
  useRetryWhenOnline(loadError, retryDescribe);

  const startUpload = (chosen: File): void => {
    setRemap(false);
    upload.mutate({ file: chosen }, { onSuccess: (created) => setJobId(created.id) });
  };

  const handleUpload = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (file === null) return;
    startUpload(file);
  };

  const handlePreview = (): void => {
    if (job === undefined) return;
    setRemap(false);
    preview.mutate({ jobId: job.id, mapping });
  };

  const startOver = (): void => {
    setJobId(undefined);
    setFile(null);
    setRemap(false);
    upload.reset();
    preview.reset();
    commit.reset();
  };

  const handleTemplate = (format: "xlsx" | "csv"): void => {
    setTemplateError(null);
    downloadImportTemplate(client, resource, format).catch((error: unknown) =>
      setTemplateError(error),
    );
  };

  const header = (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      {title !== null ? <h3 className="text-base font-semibold">{title}</h3> : null}
      {describe.data !== undefined ? (
        <div className="flex items-baseline gap-3 text-sm">
          <Button
            variant="link"
            size="sm"
            className="h-auto px-0 underline"
            onClick={() => handleTemplate("xlsx")}
          >
            Download template (XLSX)
          </Button>
          <Button
            variant="link"
            size="sm"
            className="h-auto px-0 underline"
            aria-label="CSV template"
            onClick={() => handleTemplate("csv")}
          >
            CSV
          </Button>
        </div>
      ) : describeLoading ? (
        // Where the template links will be, so they do not push the form down on a phone.
        <Skeleton className={cn("h-5 w-56", !slow && "invisible")} aria-hidden="true" />
      ) : null}
    </div>
  );

  let body: React.ReactNode;
  if (loadError !== null && loadError !== undefined) {
    // Without the description there is nothing to upload against: no form.
    body = (
      <Slots.Error
        error={loadError}
        context={{ action: "import", resource: label }}
        onRetry={retryDescribe}
        retrying={describe.isFetching}
      />
    );
  } else if (describeOffline) {
    body = (
      <Slots.Error
        error={offlineError()}
        context={{ action: "import", resource: label }}
        onRetry={retryDescribe}
        retrying={false}
      />
    );
  } else if (describe.data === undefined) {
    body = (
      <>
        <span role="status" className="sr-only">
          {slow ? "Loading the import form…" : ""}
        </span>
        <Slots.Loading slow={slow} />
      </>
    );
  } else if (step === "upload") {
    const uploadError = upload.error;
    body = (
      <div className="space-y-3">
        <form onSubmit={handleUpload} className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid w-full max-w-96 gap-1.5">
              <Label htmlFor={fileId}>File to import</Label>
              <Input
                id={fileId}
                type="file"
                name="file"
                accept=".csv,.xlsx"
                required
                className="cursor-pointer"
                aria-describedby={hintId}
                aria-invalid={
                  uploadError != null && describeError(uploadError).kind === "validation"
                    ? true
                    : undefined
                }
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <PendingButton type="submit" pending={upload.isPending} pendingLabel="Uploading…">
              Upload
            </PendingButton>
          </div>
          <p id={hintId} className="text-xs text-muted-foreground">
            CSV or XLSX with a header row, up to {describe.data.max_rows.toLocaleString()} rows. The
            template lists the columns.
          </p>
        </form>
        {upload.isPaused ? <WaitingForConnection what="file" /> : null}
        {uploadError !== null && uploadError !== undefined ? (
          <div ref={uploadErrorRef} tabIndex={-1} className="focus:outline-none">
            <Slots.Error
              error={uploadError}
              context={{ action: "upload", resource: label }}
              onRetry={file !== null ? () => startUpload(file) : undefined}
              retrying={upload.isPending}
            />
          </div>
        ) : null}
      </div>
    );
  } else if (job === undefined) {
    body = null; // unreachable: step "upload" covers a missing job
  } else if (step === "progress") {
    body = <Slots.Progress job={job} />;
  } else if (step === "map") {
    const fields = job.fields ?? describe.data.fields;
    body = (
      <div className="space-y-3">
        {job.error !== null ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-destructive-border bg-destructive-subtle p-3 text-sm"
          >
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <div className="space-y-1">
              <p className="font-medium text-foreground">The import failed</p>
              <p className="text-muted-foreground">{job.error}</p>
            </div>
          </div>
        ) : null}
        <p className="text-sm text-muted-foreground">
          {job.file_name} has {job.rows_total} rows. Map each column to a field. Blank cells leave a
          field unchanged.
        </p>
        <MappingTable
          job={job}
          fields={fields}
          mapping={mapping}
          onChange={(header, field) => setMapping((old) => ({ ...old, [header]: field }))}
        />
        {preview.isPaused ? <WaitingForConnection what="preview" /> : null}
        {preview.error !== null && preview.error !== undefined ? (
          <Slots.Error
            error={preview.error}
            context={{ action: "preview", resource: label }}
            onRetry={handlePreview}
            retrying={preview.isPending}
          />
        ) : null}
        <div className="flex flex-wrap gap-2">
          <PendingButton
            onClick={handlePreview}
            pending={preview.isPending}
            pendingLabel="Previewing…"
          >
            Preview
          </PendingButton>
          <Button variant="outline" onClick={startOver} disabled={busy}>
            Upload another file
          </Button>
        </div>
      </div>
    );
  } else {
    const result = job.result;
    const done = step === "done";
    body = (
      <div className="space-y-3">
        <p role="status" className="text-sm text-muted-foreground">
          {done ? "Imported" : "Previewed"} {job.file_name} ({job.rows_total} rows).
          {done ? null : " Nothing is saved yet."}
        </p>
        {result !== null ? <Slots.Summary job={job} result={result} /> : null}
        {job.problems.length > 0 ? <Slots.Problems job={job} problems={job.problems} /> : null}
        <div className="flex flex-wrap gap-2">
          {done ? (
            <Button variant="outline" onClick={startOver}>
              Import another file
            </Button>
          ) : (
            <>
              <Button
                ref={commitButtonRef}
                onClick={() => {
                  commit.reset();
                  setConfirmOpen(true);
                }}
                disabled={busy || result === null}
              >
                Commit
              </Button>
              <Button variant="outline" onClick={() => setRemap(true)} disabled={busy}>
                Change the mapping
              </Button>
            </>
          )}
        </div>
        {!done && result !== null ? (
          <Slots.ConfirmCommit
            open={confirmOpen}
            onOpenChange={(open) => {
              if (!commit.isPending) setConfirmOpen(open);
            }}
            job={job}
            result={result}
            resourceLabel={label}
            pending={commit.isPending}
            error={commit.isPaused ? offlineError() : commit.error}
            onConfirm={() =>
              commit.mutate(job.id, {
                onSuccess: () => setConfirmOpen(false),
              })
            }
          />
        ) : null}
      </div>
    );
  }

  return (
    <section
      className={cn("space-y-3", className)}
      aria-label="Import"
      aria-busy={describeLoading || undefined}
    >
      {header}
      {templateError !== null ? (
        <ErrorState
          variant="inline"
          error={templateError}
          context={{ action: "download the template for", resource: label }}
        />
      ) : null}
      <div ref={stepRef} tabIndex={-1} className="focus:outline-none" data-step={step}>
        {body}
      </div>
    </section>
  );
}
