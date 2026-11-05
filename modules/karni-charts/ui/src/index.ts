/**
 * @karni/charts-ui public barrel (experimental).
 *
 * Explicit exports only, mirroring @karni/ui's barrel conventions.
 */
export { SavedChart } from "./SavedChart";
export type { SavedChartErrorProps, SavedChartProps, SavedChartSlots } from "./SavedChart";

export { RESOURCE, savedChartKey, savedChartQuery, useSavedChart } from "./hooks";
export type { SavedChartData, SavedChartDefinition } from "./types";

export { CHART_COMPONENT_ROLES, registerChartRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";
