/**
 * Experimental. The reports a person may run (`GET /orders/reports/`): pick
 * one, set the days and how to group them for a dated report, read the table
 * with its totals and download it as a CSV file. The chosen report is kept in
 * the `report` search value, so a reload keeps it.
 */
import {
  Button,
  cn,
  EmptyState,
  ErrorState,
  Input,
  Page,
  PendingButton,
  Skeleton,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { problemOf } from "./cart";
import { Money } from "./Money";
import type { ReportColumn, ReportInfo, ReportResult } from "./types";

export interface ReportsPageProps {
  title?: string;
  siteName?: string;
}

const BY_CHOICES = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
] as const;

function isoDay(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The last 30 days, today included. */
function lastThirtyDays(): { start: string; end: string } {
  const today = new Date();
  const first = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 29);
  return { start: isoDay(first), end: isoDay(today) };
}

function readChosen(): string {
  try {
    return new URLSearchParams(window.location.search).get("report") ?? "";
  } catch {
    return "";
  }
}

function keepChosen(key: string): void {
  try {
    const url = new URL(window.location.href);
    if (key) url.searchParams.set("report", key);
    else url.searchParams.delete("report");
    window.history.replaceState(window.history.state, "", url);
  } catch {
    // the address cannot change here: the choice lasts for this page only
  }
}

function numeric(column: ReportColumn): boolean {
  return column.format === "money" || column.format === "number";
}

function dayText(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])).toLocaleDateString();
}

function Cell({
  column,
  value,
  currency,
}: {
  column: ReportColumn;
  value: string | number | null | undefined;
  currency: string;
}) {
  if (value === null || value === undefined || value === "") return <>{""}</>;
  if (column.format === "money") return <Money value={value} currency={currency} />;
  if (column.format === "number") {
    const amount = Number(value);
    return <>{Number.isFinite(amount) ? amount.toLocaleString() : String(value)}</>;
  }
  if (column.format === "date") return <>{dayText(String(value))}</>;
  return <>{String(value)}</>;
}

function fileNameOf(response: Response, fallback: string): string {
  const header = response.headers.get("content-disposition") ?? "";
  return /filename="?([^";]+)"?/i.exec(header)?.[1] ?? fallback;
}

function saveFile(blob: Blob, name: string): void {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function ReportView({ info, onBack }: { info: ReportInfo; onBack: () => void }) {
  const client = useKarniClient();
  const ids = { start: useId(), end: useId(), by: useId() };
  const [range, setRange] = useState(lastThirtyDays);
  const [by, setBy] = useState<string>("day");
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState("");
  const query = info.dated ? { start: range.start, end: range.end, by } : {};
  const result = useQuery<ReportResult>({
    queryKey: ["karni-commerce", "report", info.key, query],
    queryFn: ({ signal }) =>
      client.request<ReportResult>(`/orders/reports/${encodeURIComponent(info.key)}/`, {
        query,
        signal,
      }),
  });
  const download = () => {
    setSaving(true);
    setFailure("");
    client
      .requestRaw(`/orders/reports/${encodeURIComponent(info.key)}/`, {
        query: { ...query, export: "csv" },
      })
      .then(async (response) => {
        saveFile(await response.blob(), fileNameOf(response, `${info.key}.csv`));
      })
      .catch((error: unknown) => setFailure(problemOf(error)))
      .finally(() => setSaving(false));
  };
  const data = result.data;
  const totals = data?.totals ?? {};
  const hasTotals = Object.keys(totals).length > 0;
  return (
    <section className="space-y-4" aria-label={info.title}>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={onBack}>
          All reports
        </Button>
        <h2 className="text-xl font-semibold">{info.title}</h2>
      </div>
      <p className="text-sm text-muted-foreground">{info.describe}</p>
      <div className="flex flex-wrap items-end gap-3">
        {info.dated ? (
          <>
            <div className="space-y-1">
              <label htmlFor={ids.start} className="text-sm font-medium">
                From
              </label>
              <Input
                id={ids.start}
                type="date"
                value={range.start}
                max={range.end}
                onChange={(event) => setRange({ ...range, start: event.target.value })}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor={ids.end} className="text-sm font-medium">
                To
              </label>
              <Input
                id={ids.end}
                type="date"
                value={range.end}
                min={range.start}
                onChange={(event) => setRange({ ...range, end: event.target.value })}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor={ids.by} className="text-sm font-medium">
                By
              </label>
              <select
                id={ids.by}
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={by}
                onChange={(event) => setBy(event.target.value)}
              >
                {BY_CHOICES.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </div>
          </>
        ) : null}
        <PendingButton variant="outline" pending={saving} onClick={download}>
          Download CSV
        </PendingButton>
      </div>
      {failure ? (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      ) : null}
      {result.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : result.isError ? (
        <ErrorState error={result.error} onRetry={() => void result.refetch()} />
      ) : data && data.rows.length === 0 ? (
        <EmptyState title="Nothing in these days" description="Try a longer range." />
      ) : data ? (
        <div className="max-w-full overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <caption className="sr-only">{data.title}</caption>
            <thead className="bg-muted text-left text-muted-foreground">
              <tr>
                {data.columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap p-3 font-medium",
                      numeric(column) && "text-right",
                    )}
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, index) => (
                <tr key={index} className="border-t border-border">
                  {data.columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn("p-3", numeric(column) && "text-right tabular-nums")}
                    >
                      <Cell column={column} value={row[column.key]} currency={data.currency} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            {hasTotals ? (
              <tfoot className="border-t-2 border-border font-semibold">
                <tr>
                  {data.columns.map((column, index) => (
                    <td
                      key={column.key}
                      className={cn("p-3", numeric(column) && "text-right tabular-nums")}
                    >
                      {index === 0 ? (
                        "Total"
                      ) : (
                        <Cell column={column} value={totals[column.key]} currency={data.currency} />
                      )}
                    </td>
                  ))}
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function ReportsPage({ title = "Reports", siteName }: ReportsPageProps) {
  const client = useKarniClient();
  const [chosen, setChosen] = useState(readChosen);
  usePageMeta({ title, siteName });
  const list = useQuery<ReportInfo[]>({
    queryKey: ["karni-commerce", "reports"],
    queryFn: ({ signal }) => client.request<ReportInfo[]>("/orders/reports/", { signal }),
  });
  const choose = (key: string) => {
    setChosen(key);
    keepChosen(key);
  };
  const info = list.data?.find((report) => report.key === chosen);
  return (
    <Page title={title}>
      {list.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.length === 0 ? (
        <EmptyState title="No reports for you" />
      ) : info ? (
        <ReportView key={info.key} info={info} onBack={() => choose("")} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {list.data.map((report) => (
            <li key={report.key}>
              <button
                type="button"
                className="h-full w-full rounded-lg border border-border p-4 text-left hover:border-primary"
                onClick={() => choose(report.key)}
              >
                <span className="block font-semibold">{report.title}</span>
                <span className="block text-sm text-muted-foreground">{report.describe}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}
