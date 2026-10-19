import * as React from "react";
import {
  downloadImportTemplate,
  isImportInFlight,
  useImportActions,
  useImportDescribe,
  useImportJob,
  type ImportColumn,
  type ImportJob,
} from "../../../hooks/useResourceImport";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import { useKarniClient } from "../../../schema/provider";
import { Button } from "../../primitives/button";
import { Select } from "../../primitives/select";
import { Skeleton } from "../../primitives/skeleton";

registerComponentRole("resource-import", "ResourceImport");

export interface ResourceImportProps {
  resource: string;
  title?: React.ReactNode;
  /** Called when a commit finishes (the job is `done`). */
  onDone?: (job: ImportJob) => void;
  className?: string;
}

function errorText(error: unknown): string {
  if (error instanceof Error) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === "object" && data !== null && "detail" in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    return error.message;
  }
  return "Something went wrong.";
}

function Stats({ job }: { job: ImportJob }): React.ReactElement | null {
  if (job.result === null) return null;
  const { created, updated, skipped, unchanged, errors } = job.result;
  return (
    <dl className="flex flex-wrap gap-6" data-testid="import-stats">
      <div>
        <dt className="text-xs uppercase text-muted-foreground">Created</dt>
        <dd className="text-2xl font-semibold">{created}</dd>
      </div>
      <div>
        <dt className="text-xs uppercase text-muted-foreground">Updated</dt>
        <dd className="text-2xl font-semibold">{updated}</dd>
      </div>
      <div>
        <dt className="text-xs uppercase text-muted-foreground">Skipped</dt>
        <dd className="text-2xl font-semibold">
          {skipped}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            ({unchanged} unchanged, {errors} with errors)
          </span>
        </dd>
      </div>
    </dl>
  );
}

function Problems({ job }: { job: ImportJob }): React.ReactElement | null {
  if (job.problems.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm" aria-label="Rows with errors">
        <thead className="bg-muted text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Row</th>
            <th className="px-3 py-2">Field</th>
            <th className="px-3 py-2">Problem</th>
          </tr>
        </thead>
        <tbody>
          {job.problems.map((problem, index) => (
            <tr key={`${problem.row}-${problem.field}-${index}`} className="border-t border-border">
              <td className="px-3 py-2 tabular-nums">{problem.row}</td>
              <td className="px-3 py-2 font-mono text-xs">{problem.field || "—"}</td>
              <td className="px-3 py-2 text-destructive">{problem.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Progress({ job }: { job: ImportJob }): React.ReactElement {
  const percent = job.rows_total > 0 ? Math.round((job.rows_done * 100) / job.rows_total) : 0;
  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <p className="text-sm">
        {job.status === "previewing" ? "Previewing" : "Committing"}… {job.rows_done} /{" "}
        {job.rows_total} rows
      </p>
      <div className="h-2 w-full overflow-hidden rounded bg-muted">
        <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

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
      <table className="w-full text-sm" aria-label="Column mapping">
        <thead className="bg-muted text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2">Column in the file</th>
            <th className="px-3 py-2">Field</th>
          </tr>
        </thead>
        <tbody>
          {job.columns.map((header) => (
            <tr key={header} className="border-t border-border">
              <td className="px-3 py-2">{header}</td>
              <td className="px-3 py-2">
                <Select
                  aria-label={`Field for ${header}`}
                  className="h-9 w-auto min-w-48"
                  value={mapping[header] ?? ""}
                  options={options}
                  clearable
                  clearLabel="— ignore —"
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

/**
 * Import a CSV or XLSX file into a resource: upload, map columns to fields,
 * preview (the mandatory dry run — N created / updated / skipped with every
 * row's errors), then commit. Drives `/<resource>/import/…`; the backend
 * validates every row through the same serializer the API uses, keeps rows
 * inside the user's scope and refuses fields the role may not write. Large
 * files run in the background with progress.
 */
export function ResourceImport({
  resource,
  title = "Import",
  onDone,
  className,
}: ResourceImportProps): React.ReactElement {
  const client = useKarniClient();
  const describe = useImportDescribe(resource);
  const actions = useImportActions(resource);
  const [jobId, setJobId] = React.useState<string | undefined>(undefined);
  const [mapping, setMapping] = React.useState<Record<string, string>>({});
  const [remap, setRemap] = React.useState(false);
  const [templateError, setTemplateError] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
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

  const fields = job?.fields ?? describe.data?.fields ?? [];
  const busy = actions.upload.isPending || actions.preview.isPending || actions.commit.isPending;
  const mutationError = actions.upload.error ?? actions.preview.error ?? actions.commit.error;

  const handleUpload = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (file === undefined) return;
    setRemap(false);
    actions.upload.mutate({ file }, { onSuccess: (created) => setJobId(created.id) });
  };

  const handlePreview = (): void => {
    if (job === undefined) return;
    setRemap(false);
    actions.preview.mutate({ jobId: job.id, mapping });
  };

  const handleTemplate = (format: "xlsx" | "csv"): void => {
    setTemplateError(null);
    downloadImportTemplate(client, resource, format).catch((error: unknown) =>
      setTemplateError(errorText(error)),
    );
  };

  let body: React.ReactNode;
  if (describe.isPending) {
    body = <Skeleton className="h-24 w-full" data-testid="resource-import-loading" />;
  } else if (job === undefined || (jobId !== undefined && jobQuery.isPending)) {
    body = (
      <form onSubmit={handleUpload} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span>CSV or XLSX file</span>
          <input
            ref={fileRef}
            type="file"
            name="file"
            accept=".csv,.xlsx"
            required
            className="text-sm"
            aria-label="File to import"
          />
        </label>
        <Button type="submit" disabled={busy}>
          Upload
        </Button>
      </form>
    );
  } else if (isImportInFlight(job)) {
    body = <Progress job={job} />;
  } else if (job.status === "uploaded" || job.status === "failed" || remap) {
    body = (
      <div className="space-y-3">
        {job.error !== null && (
          <p role="alert" className="text-sm text-destructive">
            {job.error}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          {job.file_name} — {job.rows_total} rows. Map each column to a field; blank cells leave a
          field unchanged.
        </p>
        <MappingTable
          job={job}
          fields={fields}
          mapping={mapping}
          onChange={(header, field) => setMapping((old) => ({ ...old, [header]: field }))}
        />
        <div className="flex flex-wrap gap-2">
          <Button onClick={handlePreview} disabled={busy}>
            Preview
          </Button>
          <Button variant="outline" onClick={() => setJobId(undefined)} disabled={busy}>
            Upload another file
          </Button>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          {job.file_name} — {job.rows_total} rows,{" "}
          {job.status === "done" ? "imported." : "previewed; nothing is saved yet."}
        </p>
        <Stats job={job} />
        <Problems job={job} />
        <div className="flex flex-wrap gap-2">
          {job.status === "previewed" ? (
            <>
              <Button onClick={() => actions.commit.mutate(job.id)} disabled={busy}>
                Commit
              </Button>
              <Button variant="outline" onClick={() => setRemap(true)} disabled={busy}>
                Change the mapping
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => setJobId(undefined)}>
              Import another file
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <section className={cn("space-y-3", className)} aria-label="Import">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {title !== null ? <h3 className="text-base font-semibold">{title}</h3> : null}
        <div className="flex gap-2 text-sm">
          <button
            type="button"
            className="text-primary underline-offset-4 hover:underline"
            onClick={() => handleTemplate("xlsx")}
          >
            Download template (XLSX)
          </button>
          <button
            type="button"
            className="text-primary underline-offset-4 hover:underline"
            onClick={() => handleTemplate("csv")}
          >
            CSV
          </button>
        </div>
      </div>
      {describe.error !== null && describe.error !== undefined ? (
        <p role="alert" className="text-sm text-destructive">
          {errorText(describe.error)}
        </p>
      ) : null}
      {mutationError !== null && mutationError !== undefined ? (
        <p role="alert" className="text-sm text-destructive">
          {errorText(mutationError)}
        </p>
      ) : null}
      {templateError !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {templateError}
        </p>
      ) : null}
      {body}
    </section>
  );
}
