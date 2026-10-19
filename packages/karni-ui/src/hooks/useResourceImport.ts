/**
 * Import and export hooks (karni.transfer, ADR 0002 P6).
 *
 * - `downloadResourceExport(client, resource, params, format)` fetches
 *   `GET /<resource>/export/` with the list's own query (filters, search,
 *   ordering) and hands the file to the browser — what ResourceTable's export
 *   buttons call.
 * - `useImportDescribe(resource)` reads `GET /<resource>/import/`: the
 *   importable fields and the user's remembered mapping.
 * - `useImportJob(resource, jobId)` reads one job's state and polls while the
 *   backend is previewing or committing it in Celery.
 * - `useImportActions(resource)` holds the three mutations: upload (creates
 *   the job), preview (the mandatory dry run, with the mapping) and commit.
 *
 * The backend decides everything that matters: which fields the role may
 * write, which rows are in scope, what a row's errors are. The hooks render
 * its answers without filtering.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import type { KarniClient, KarniQueryValue } from "../schema/client";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { buildListQuery, listPath } from "./params";
import type { ResourceListParams } from "./types";

export type ExportFormat = "csv" | "xlsx";

export type ImportColumnKind =
  | "text"
  | "integer"
  | "decimal"
  | "boolean"
  | "date"
  | "datetime"
  | "choice"
  | "relation"
  | "relations"
  | "json"
  | "file"
  | "other";

export interface ImportColumn {
  name: string;
  label: string;
  kind: ImportColumnKind;
  required: boolean;
  readable: boolean;
  writable: boolean;
  choices: ReadonlyArray<{ value: string; label: string }>;
  /** `app_label.model` of a relation's target. */
  target: string | null;
  /** The target field a relation column carries (its natural key), else the id. */
  lookup: string | null;
  help: string;
  /** The column an import matches existing rows on. */
  key: boolean;
}

export interface ImportDescription {
  fields: ImportColumn[];
  /** The mapping the user last confirmed for this resource (header → field). */
  mapping: Record<string, string>;
  /** Files with more rows than this run in Celery; poll the job. */
  inline_rows: number;
  max_rows: number;
  key: string | null;
}

export type ImportStatus =
  "uploaded" | "previewing" | "previewed" | "committing" | "done" | "failed";

export interface ImportResult {
  rows_total: number;
  created: number;
  updated: number;
  unchanged: number;
  errors: number;
  skipped: number;
}

export interface ImportProblem {
  /** The line in the file (the header is line 1). */
  row: number;
  field: string;
  message: string;
}

export interface ImportJob {
  id: string;
  model: string | null;
  status: ImportStatus;
  file_name: string;
  format: string;
  columns: string[];
  mapping: Record<string, string>;
  rows_total: number;
  rows_done: number;
  async: boolean;
  result: ImportResult | null;
  problems: ImportProblem[];
  error: string | null;
  batch: number | null;
  created_at: string | null;
  fields?: ImportColumn[];
}

export function importDescribeKey(resource: string): readonly unknown[] {
  return [...karniKeys.resource(resource), "import", "describe"] as const;
}

export function importJobKey(resource: string, jobId: string): readonly unknown[] {
  return [...karniKeys.resource(resource), "import", "job", jobId] as const;
}

function importPath(resource: string, suffix = ""): string {
  return `${listPath(resource)}import/${suffix}`;
}

const IN_FLIGHT: ReadonlySet<ImportStatus> = new Set<ImportStatus>(["previewing", "committing"]);

export function isImportInFlight(job: ImportJob | undefined): boolean {
  return job !== undefined && IN_FLIGHT.has(job.status);
}

/** The name the backend suggested, else "<resource>.<format>". */
function filenameFrom(response: Response, fallback: string): string {
  const header = response.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match?.[1] ?? fallback;
}

/**
 * Fetches `GET /<resource>/export/?format=…` with the list's query and saves
 * it through a temporary object URL. Resolves with the file name. Throws the
 * `KarniApiError` the backend answered (a 400 with code E803 when the export
 * is larger than `KARNI_EXPORT_MAX_ROWS`).
 */
export async function downloadResourceExport(
  client: KarniClient,
  resource: string,
  params: ResourceListParams | undefined,
  format: ExportFormat = "csv",
): Promise<string> {
  const query: Record<string, KarniQueryValue> = { ...buildListQuery(params), format };
  delete query["page"];
  delete query["page_size"];
  const response = await client.requestRaw(`${listPath(resource)}export/`, { query });
  const blob = await response.blob();
  const filename = filenameFrom(response, `${resource}.${format}`);
  saveBlob(blob, filename);
  return filename;
}

/** Hands a blob to the browser as a download (a no-op outside a DOM, e.g. SSR). */
export function saveBlob(blob: Blob, filename: string): void {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Fetches `GET /<resource>/import/template/?format=…` and saves it (the headers, an example, allowed values). */
export async function downloadImportTemplate(
  client: KarniClient,
  resource: string,
  format: ExportFormat = "xlsx",
): Promise<string> {
  const response = await client.requestRaw(importPath(resource, "template/"), {
    query: { format },
  });
  const blob = await response.blob();
  const filename = filenameFrom(response, `${resource}-template.${format}`);
  saveBlob(blob, filename);
  return filename;
}

export function useImportDescribe(
  resource: string,
  options?: Omit<UseQueryOptions<ImportDescription>, "queryKey" | "queryFn">,
): UseQueryResult<ImportDescription> {
  const client = useKarniClient();
  return useQuery<ImportDescription>({
    ...options,
    queryKey: importDescribeKey(resource),
    queryFn: ({ signal }) => client.request<ImportDescription>(importPath(resource), { signal }),
  });
}

export interface UseImportJobOptions {
  /** Polling interval while the job is previewing/committing. Default 1500 ms. */
  pollMs?: number;
}

export function useImportJob(
  resource: string,
  jobId: string | undefined,
  options?: UseImportJobOptions,
): UseQueryResult<ImportJob> {
  const client = useKarniClient();
  const pollMs = options?.pollMs ?? 1500;
  return useQuery<ImportJob>({
    queryKey: importJobKey(resource, jobId ?? ""),
    enabled: jobId !== undefined,
    queryFn: ({ signal }) =>
      client.request<ImportJob>(importPath(resource, `${encodeURIComponent(jobId ?? "")}/`), {
        signal,
      }),
    refetchInterval: (query) => (isImportInFlight(query.state.data) ? pollMs : false),
  });
}

export interface UploadImportInput {
  file: File;
  /** An explicit mapping; otherwise the backend suggests or remembers one. */
  mapping?: Record<string, string>;
}

export interface PreviewImportInput {
  jobId: string;
  mapping: Record<string, string>;
}

export interface ImportActions {
  upload: UseMutationResult<ImportJob, unknown, UploadImportInput>;
  preview: UseMutationResult<ImportJob, unknown, PreviewImportInput>;
  commit: UseMutationResult<ImportJob, unknown, string>;
}

export function useImportActions(resource: string): ImportActions {
  const client = useKarniClient();
  const queryClient = useQueryClient();

  const store = (job: ImportJob): ImportJob => {
    queryClient.setQueryData(importJobKey(resource, job.id), job);
    return job;
  };

  const upload = useMutation<ImportJob, unknown, UploadImportInput>({
    mutationFn: async ({ file, mapping }) => {
      const form = new FormData();
      form.append("file", file);
      if (mapping !== undefined) form.append("mapping", JSON.stringify(mapping));
      return store(
        await client.request<ImportJob>(importPath(resource), { method: "POST", body: form }),
      );
    },
  });

  const preview = useMutation<ImportJob, unknown, PreviewImportInput>({
    mutationFn: async ({ jobId, mapping }) =>
      store(
        await client.request<ImportJob>(
          importPath(resource, `${encodeURIComponent(jobId)}/preview/`),
          {
            method: "POST",
            body: { mapping },
          },
        ),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: importDescribeKey(resource) });
    },
  });

  const commit = useMutation<ImportJob, unknown, string>({
    mutationFn: async (jobId) =>
      store(
        await client.request<ImportJob>(
          importPath(resource, `${encodeURIComponent(jobId)}/commit/`),
          {
            method: "POST",
            body: {},
          },
        ),
      ),
    onSuccess: (job) => {
      if (job.status === "done") {
        void queryClient.invalidateQueries({ queryKey: karniKeys.resource(resource) });
      }
    },
  });

  return { upload, preview, commit };
}
