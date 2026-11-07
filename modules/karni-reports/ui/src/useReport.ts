/**
 * useReport: request, follow and download the PDF report of one row.
 *
 * Experimental. `request()` posts `/reports/<report>/<id>/`. A file ready at
 * the current cache key comes back at once; otherwise the hook polls
 * `.../status/` every `pollInterval` milliseconds until the file is ready or
 * failed. `download()` fetches `.../download/` with the client's auth and
 * hands the blob to `save` (a browser download by default).
 *
 * The state lives in TanStack Query under `reportKey(report, objectId)`, so
 * two components showing the same report share it.
 *
 * Escape hatches: `save` replaces the browser download, `pollInterval` the
 * polling rate, `watch` loads the status on mount without requesting.
 */
import { karniKeys, useKarniClient } from "@karni/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { isReportInFlight, type ReportState, type ReportStatusValue } from "./types";

export interface UseReportOptions {
  /** Milliseconds between status checks while the file renders. Default 1500. */
  pollInterval?: number;
  /** Load the last request's status on mount, without requesting. Default false. */
  watch?: boolean;
  /** Saves a downloaded file. Default: a temporary link, so the browser downloads it. */
  save?: (blob: Blob, filename: string) => void;
}

export interface UseReportResult {
  /** The last state the API answered, or undefined before the first answer. */
  state: ReportState | undefined;
  /** `idle` before any answer, else the report's status. */
  status: ReportStatusValue | "idle";
  /** True while the request is on its way or the file renders. */
  isWorking: boolean;
  /** The last error a request, a status check or a download threw (a KarniApiError for the API). */
  error: unknown;
  /** Request the report. Resolves with the API's answer (status `ready` when cached). */
  request: () => Promise<ReportState>;
  /** Download the ready file. Resolves with the file name. */
  download: () => Promise<string>;
}

const DEFAULT_POLL_INTERVAL = 1500;

/** Experimental. The query key of one report of one row. */
export function reportKey(report: string, objectId: string | number): readonly unknown[] {
  return [...karniKeys.resource("reports"), report, String(objectId)];
}

/** Experimental. The API path of one report of one row: `/reports/<report>/<id>/`. */
export function reportPath(report: string, objectId: string | number): string {
  return `/reports/${encodeURIComponent(report)}/${encodeURIComponent(String(objectId))}/`;
}

/** The name the backend suggested in Content-Disposition, else the fallback. */
function filenameFrom(response: Response, fallback: string): string {
  const header = response.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match?.[1] ?? fallback;
}

/** Hands a blob to the browser as a download (a no-op outside a DOM). */
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

/** Experimental. Request, follow and download the report `report` of the row `objectId`. */
export function useReport(
  report: string,
  objectId: string | number,
  options: UseReportOptions = {},
): UseReportResult {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const key = reportKey(report, objectId);
  const path = reportPath(report, objectId);
  const pollInterval = options.pollInterval ?? DEFAULT_POLL_INTERVAL;
  const [following, setFollowing] = useState(options.watch === true);
  const [downloadError, setDownloadError] = useState<unknown>(null);

  const status = useQuery({
    queryKey: key,
    queryFn: () => client.request<ReportState>(`${path}status/`),
    enabled: following,
    // A fresh answer from request() is not fetched again at once; polling still runs.
    staleTime: pollInterval,
    refetchInterval: (query) => (isReportInFlight(query.state.data) ? pollInterval : false),
  });

  const requestMutation = useMutation({
    mutationFn: () => client.request<ReportState>(path, { method: "POST" }),
    onSuccess: (answer) => {
      queryClient.setQueryData(key, answer);
      setFollowing(true);
    },
  });

  const { mutateAsync } = requestMutation;
  const request = useCallback(async (): Promise<ReportState> => {
    setDownloadError(null);
    return mutateAsync();
  }, [mutateAsync]);

  const save = options.save ?? saveBlob;
  const download = useCallback(async (): Promise<string> => {
    try {
      const response = await client.requestRaw(`${path}download/`);
      const blob = await response.blob();
      const filename = filenameFrom(response, `${report}-${String(objectId)}.pdf`);
      save(blob, filename);
      return filename;
    } catch (caught) {
      setDownloadError(caught);
      throw caught;
    }
  }, [client, path, report, objectId, save]);

  const state = status.data;
  return {
    state,
    status: state?.status ?? "idle",
    isWorking: requestMutation.isPending || isReportInFlight(state),
    error: requestMutation.error ?? status.error ?? downloadError,
    request,
    download,
  };
}
