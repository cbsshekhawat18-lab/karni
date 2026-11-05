/**
 * @karni/reports-ui public barrel (experimental).
 *
 * Explicit exports only, mirroring @karni/ui's barrel conventions. Importing
 * the package registers the `report-button` component role when @karni/ui
 * has the registry.
 */
import { registerReportRoles } from "./roles";

export { ReportButton } from "./ReportButton";
export type { ReportButtonLabels, ReportButtonProps } from "./ReportButton";

export { reportKey, reportPath, saveBlob, useReport } from "./useReport";
export type { UseReportOptions, UseReportResult } from "./useReport";

export { REPORT_STATUSES, isReportInFlight } from "./types";
export type { ReportState, ReportStatusValue } from "./types";

export { REPORT_COMPONENT_ROLES, registerReportRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";

registerReportRoles();
