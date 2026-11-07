/**
 * Shared report types for @karni/reports-ui.
 *
 * Experimental. `ReportState` is what `POST /api/reports/<report>/<id>/` and
 * `GET /api/reports/<report>/<id>/status/` answer (karni_reports'
 * ReportStatusSerializer).
 */

/** Experimental. The statuses of a report. `none`: never requested for this row. */
export const REPORT_STATUSES = ["none", "pending", "rendering", "ready", "failed"] as const;

export type ReportStatusValue = (typeof REPORT_STATUSES)[number];

/** Experimental. One report of one row, as the API answers it. */
export interface ReportState {
  id: string | null;
  report: string;
  object_id: string;
  status: ReportStatusValue;
  /** The download path, set only while the file is ready. */
  url: string | null;
  /** Bytes of the file (0 before it renders). */
  size: number;
  data_version: string;
  /** A fixed sentence when the render failed. Staff read the cause in the admin. */
  error: string;
  requested_at: string | null;
  rendered_at: string | null;
  created_at: string | null;
}

/** True while the file is queued or rendering: the states worth polling. */
export function isReportInFlight(state: ReportState | undefined): boolean {
  return state !== undefined && (state.status === "pending" || state.status === "rendering");
}
