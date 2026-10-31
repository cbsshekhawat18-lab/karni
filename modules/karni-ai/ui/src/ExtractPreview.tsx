/**
 * <ExtractPreview>: the import preview of an extraction, and its commit. Experimental.
 *
 * Shows the proposed rows, a problem per field (found while reading the
 * answer, or by the import's dry run), the preview's counts, and Commit,
 * which confirms through `@karni/ui`'s `useImportActions(resource).commit`:
 * the import's own commit path. Nothing is saved before that.
 *
 * The counts and the confirmation reuse `@karni/ui`'s import slots
 * (`defaultResourceImportSlots.Summary` and `.ConfirmCommit`), so an
 * extraction reads like a file import. Escape hatch: replace any part with
 * `slots` (Rows, Problems, Summary, ConfirmCommit).
 */
import {
  Button,
  EmptyValue,
  defaultResourceImportSlots,
  useImportActions,
  useImportJob,
  type ImportConfirmProps,
  type ImportJob,
  type ImportSummaryProps,
} from "@karni/ui";
import * as React from "react";
import type { ExtractProblem, ExtractResult } from "./types";

/** What the `Rows` slot receives: the proposed rows and the fields they use, in order. */
export interface ExtractRowsProps {
  rows: ReadonlyArray<Record<string, unknown>>;
  fields: readonly string[];
}

/** What the `Problems` slot receives: one problem per field, rows numbered from 1. */
export interface ExtractProblemsProps {
  problems: readonly ExtractProblem[];
}

/** The replaceable parts of ExtractPreview. */
export interface ExtractPreviewSlots {
  Rows: React.ComponentType<ExtractRowsProps>;
  Problems: React.ComponentType<ExtractProblemsProps>;
  Summary: React.ComponentType<ImportSummaryProps>;
  ConfirmCommit: React.ComponentType<ImportConfirmProps>;
}

export interface ExtractPreviewProps {
  /** The answer of `useExtract`. */
  result: ExtractResult;
  /** The resource in words, plural ("products"). Default: the router prefix. */
  resourceLabel?: string;
  /** Called once the commit saved the rows (the job is `done`). */
  onDone?: (job: ImportJob) => void;
  /** Shown as "Read another source" when given. */
  onStartOver?: () => void;
  slots?: Partial<ExtractPreviewSlots>;
}

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

function cell(value: unknown): React.ReactNode {
  if (value === undefined || value === null || value === "") return <EmptyValue />;
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The fields the rows use, in the order they first appear. */
export function rowFields(rows: ReadonlyArray<Record<string, unknown>>): string[] {
  const seen: string[] = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) if (!seen.includes(key)) seen.push(key);
  }
  return seen;
}

function DefaultRows({ rows, fields }: ExtractRowsProps): React.ReactElement {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <caption className="px-3 py-2 text-left text-sm font-medium text-foreground">
          Proposed rows
        </caption>
        <thead className="bg-muted text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">
              Row
            </th>
            {fields.map((field) => (
              <th key={field} scope="col" className="px-3 py-2 font-medium">
                {field}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-border">
              <th scope="row" className="px-3 py-2 text-left font-normal tabular-nums">
                {index + 1}
              </th>
              {fields.map((field) => (
                <td key={field} className="px-3 py-2">
                  {cell(row[field])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const FOUND_BY: Record<ExtractProblem["source"], string> = {
  schema: "Reading",
  preview: "Preview",
};

function DefaultProblems({ problems }: ExtractProblemsProps): React.ReactElement {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <caption className="px-3 py-2 text-left text-sm font-medium text-foreground">
          Problems
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
            <th scope="col" className="px-3 py-2 font-medium">
              Found by
            </th>
          </tr>
        </thead>
        <tbody>
          {problems.map((problem, index) => (
            <tr key={`${problem.row}-${problem.field}-${index}`} className="border-t border-border">
              <th scope="row" className="px-3 py-2 text-left font-normal tabular-nums">
                {problem.row > 0 ? problem.row : <EmptyValue label="every row" />}
              </th>
              <td className="px-3 py-2 font-mono text-xs">
                {problem.field || <EmptyValue label="the whole row" />}
              </td>
              <td className="px-3 py-2">{problem.message}</td>
              <td className="px-3 py-2 text-muted-foreground">{FOUND_BY[problem.source]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultExtractPreviewSlots: ExtractPreviewSlots = {
  Rows: DefaultRows,
  Problems: DefaultProblems,
  Summary: defaultResourceImportSlots.Summary,
  ConfirmCommit: defaultResourceImportSlots.ConfirmCommit,
};

/** Experimental. The preview of an extraction, with the import's own commit. */
export function ExtractPreview({
  result,
  resourceLabel,
  onDone,
  onStartOver,
  slots,
}: ExtractPreviewProps): React.ReactElement {
  const Slots: ExtractPreviewSlots = { ...defaultExtractPreviewSlots, ...slots };
  const label = resourceLabel ?? result.resource;
  const jobQuery = useImportJob(result.resource, result.id);
  const job = jobQuery.data ?? result.job;
  const { commit } = useImportActions(result.resource);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const done = job.status === "done";
  const counts = job.result ?? result.result;
  const fields = React.useMemo(() => rowFields(result.rows), [result.rows]);

  React.useEffect(() => {
    if (done) onDone?.(job);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fire once per completion
  }, [done, job.id]);

  return (
    <section className="space-y-3" aria-label="Extraction preview" data-step={job.status}>
      <p role="status" className="text-sm text-muted-foreground">
        {done
          ? `Saved to ${label}: ${plural(
              (counts?.created ?? 0) + (counts?.updated ?? 0),
              "row",
              "rows",
            )}.`
          : `Read ${plural(result.rows.length, "row", "rows")} from ${result.source.label}. Nothing is saved yet.`}
      </p>
      {result.rows.length > 0 ? <Slots.Rows rows={result.rows} fields={fields} /> : null}
      {counts !== null ? <Slots.Summary job={job} result={counts} /> : null}
      {result.problems.length > 0 && !done ? <Slots.Problems problems={result.problems} /> : null}
      <div className="flex flex-wrap gap-2">
        {done ? null : (
          <Button
            onClick={() => {
              commit.reset();
              setConfirmOpen(true);
            }}
            disabled={commit.isPending || counts === null || job.status !== "previewed"}
          >
            Commit
          </Button>
        )}
        {onStartOver !== undefined ? (
          <Button variant="outline" onClick={onStartOver} disabled={commit.isPending}>
            Read another source
          </Button>
        ) : null}
      </div>
      {!done && counts !== null ? (
        <Slots.ConfirmCommit
          open={confirmOpen}
          onOpenChange={(open) => {
            if (!commit.isPending) setConfirmOpen(open);
          }}
          job={job}
          result={counts}
          resourceLabel={label}
          pending={commit.isPending}
          error={commit.error}
          onConfirm={() => commit.mutate(job.id, { onSuccess: () => setConfirmOpen(false) })}
        />
      ) : null}
    </section>
  );
}
