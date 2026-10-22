/**
 * @karni/ui public barrel.
 *
 * Every public name of the package is re-exported here, explicitly, so that
 * scripts/generate-manifest.mjs can parse this file and emit dist/manifest.json
 * (contract D7). Keep exports in the explicit `export { ... } from` /
 * `export type { ... } from` form, never `export *`.
 */

// lib
export { cn } from "./lib/cn";
export { registerComponentRole, getRoleRegistry } from "./lib/roles";
export type { RegisterComponentRoleOptions } from "./lib/roles";
export { variants } from "./lib/variants";
export type {
  VariantShape,
  VariantSelection,
  VariantsConfig,
  VariantFn,
  VariantProps,
} from "./lib/variants";

// unhappy states: plain-words errors, permission, slow and offline work
export { describeError, errorSummary } from "./states/describe-error";
export type {
  KarniErrorContext,
  KarniErrorDescription,
  KarniErrorKind,
} from "./states/describe-error";
export { ErrorState, PermissionDenied } from "./states/ErrorState";
export type { ErrorSlotProps, ErrorStateProps, PermissionDeniedProps } from "./states/ErrorState";
export { PendingButton } from "./states/PendingButton";
export type { PendingButtonProps } from "./states/PendingButton";
export { SLOW_AFTER_MS, useDelayedFlag, useOnlineStatus } from "./states/hooks";

// theme: light, dark or the system's choice
export {
  KARNI_THEME_SCRIPT,
  THEME_STORAGE_KEY,
  ThemeProvider,
  ThemeToggle,
  useTheme,
} from "./theme/theme";
export type {
  ResolvedTheme,
  ThemePreference,
  ThemeProviderProps,
  ThemeToggleProps,
} from "./theme/theme";

// primitives (each defers to the project's own through the registry)
export { KarniPrimitivesProvider, useKarniPrimitives } from "./primitives/registry";
export type {
  KarniPrimitiveOverrides,
  KarniPrimitiveRole,
  KarniPrimitives,
  KarniPrimitivesProviderProps,
  KarniSelectParts,
} from "./primitives/registry";
export { Button, buttonVariants } from "./components/primitives/button";
export type { ButtonProps, ButtonVariantProps } from "./components/primitives/button";

export { Input } from "./components/primitives/input";
export type { InputProps } from "./components/primitives/input";

export { Textarea } from "./components/primitives/textarea";
export type { TextareaProps } from "./components/primitives/textarea";

export {
  Select,
  SelectRoot,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  KARNI_SELECT_EMPTY,
} from "./components/primitives/select";
export type { SelectOption, SelectProps } from "./components/primitives/select";

export { Checkbox } from "./components/primitives/checkbox";
export type { CheckboxProps } from "./components/primitives/checkbox";

export { Switch } from "./components/primitives/switch";
export type { SwitchProps } from "./components/primitives/switch";

export { Label } from "./components/primitives/label";
export type { LabelProps } from "./components/primitives/label";

export { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/primitives/tabs";

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuGroup,
  DropdownMenuPortal,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "./components/primitives/dropdown-menu";

export { Skeleton } from "./components/primitives/skeleton";
export type { SkeletonProps } from "./components/primitives/skeleton";

// resource components
export { ResourceTable } from "./components/resource/ResourceTable";
export type {
  ResourceTableProps,
  ResourceColumn,
  BulkAction,
} from "./components/resource/ResourceTable";
export {
  createHistoryStateStore,
  defaultResourceTableSlots,
} from "./components/resource/ResourceTable";
export type {
  BulkActionReturn,
  BulkOutcome,
  BulkResult,
  ResourceTableActiveFilter,
  ResourceTableBulkActionsProps,
  ResourceTableCardField,
  ResourceTableDensity,
  ResourceTableForbiddenProps,
  ResourceTableLoadingProps,
  ResourceTableNoRecordsProps,
  ResourceTableNoResultsProps,
  ResourceTableOfflineProps,
  ResourceTablePaginationProps,
  ResourceTableRowCardProps,
  ResourceTableSlots,
  ResourceTableStateStore,
} from "./components/resource/ResourceTable";
export type { KarniAccessRule } from "./schema/types";

export { ResourceForm, defaultResourceFormSlots } from "./components/resource/ResourceForm";
export type {
  ResourceFormProps,
  ResourceFormSlots,
  ResourceFormErrorSummaryProps,
  ResourceFormFieldError,
  ResourceFormForbiddenProps,
  ResourceFormLoadingProps,
  ResourceFormSubmitErrorProps,
  FieldOverride,
  KarniFieldProps,
} from "./components/resource/ResourceForm";
export { UNSAVED_CHANGES_MESSAGE, useUnsavedChangesGuard } from "./hooks/useUnsavedChangesGuard";
export type {
  UnsavedChangesGuard,
  UseUnsavedChangesGuardOptions,
} from "./hooks/useUnsavedChangesGuard";

export { ResourceDetail, defaultResourceDetailSlots } from "./components/resource/ResourceDetail";
export type {
  ResourceDetailProps,
  ResourceDetailFieldOverride,
  ResourceDetailSlots,
  ResourceDetailLoadingProps,
  ResourceDetailErrorProps,
  ResourceDetailNotFoundProps,
  ResourceDetailDeletedProps,
  ResourceDetailEmptyValueProps,
  ResourceDetailDeleteDialogProps,
} from "./components/resource/ResourceDetail";

export { ResourceSelect, defaultResourceSelectSlots } from "./components/resource/ResourceSelect";
export type {
  ResourceSelectProps,
  ResourceSelectSlots,
  ResourceSelectChipProps,
  ResourceSelectEmptyProps,
  ResourceSelectLoadingProps,
  ResourceSelectOptionProps,
} from "./components/resource/ResourceSelect";

export {
  ChangeHistory,
  defaultChangeHistorySlots,
} from "./components/resource/history/ChangeHistory";
export type {
  ChangeHistoryProps,
  ChangeHistorySlots,
  ChangeHistoryLoadingProps,
  ChangeHistoryEmptyProps,
  ChangeHistoryEntryProps,
} from "./components/resource/history/ChangeHistory";
export { useChangeHistory, changeHistoryKey } from "./hooks/useChangeHistory";
export type {
  ChangeAction,
  ChangeLogEntry,
  ChangeHistoryPage,
  ChangeHistoryParams,
} from "./hooks/useChangeHistory";

export {
  ResourceImport,
  defaultResourceImportSlots,
} from "./components/resource/import/ResourceImport";
export type {
  ResourceImportProps,
  ResourceImportSlots,
  ResourceImportLoadingProps,
  ImportProgressProps,
  ImportSummaryProps,
  ImportProblemsProps,
  ImportConfirmProps,
} from "./components/resource/import/ResourceImport";
export {
  useImportDescribe,
  useImportJob,
  useImportActions,
  downloadResourceExport,
  downloadImportTemplate,
  importDescribeKey,
  importJobKey,
  isImportInFlight,
} from "./hooks/useResourceImport";
export type {
  ExportFormat,
  ImportActions,
  ImportColumn,
  ImportColumnKind,
  ImportDescription,
  ImportJob,
  ImportProblem,
  ImportResult,
  ImportStatus,
  PreviewImportInput,
  UploadImportInput,
  UseImportJobOptions,
} from "./hooks/useResourceImport";

export { displayLabel } from "./components/resource/displayLabel";
export { EmptyValue, EMPTY_VALUE_LABEL } from "./components/resource/empty-value";
export type { EmptyValueProps } from "./components/resource/empty-value";
export { AUDIT_FIELDS } from "./components/resource/audit-fields";

// hooks
export { karniKeys } from "./hooks/keys";
export { useResourceList } from "./hooks/useResourceList";
export { useResourceItem } from "./hooks/useResourceItem";
export { useResourceMutations } from "./hooks/useResourceMutations";
export type { ResourceMutations } from "./hooks/useResourceMutations";
export type {
  Paginated,
  FilterValue,
  ResourceListParams,
  ResourceItemParams,
  ResourceMutationsOptions,
} from "./hooks/types";

// schema client
export { createKarniClient, KarniApiError } from "./schema/client";
export type {
  KarniClient,
  KarniClientOptions,
  KarniQueryValue,
  KarniRequestOptions,
} from "./schema/client";

export { KarniProvider, useKarniClient } from "./schema/provider";
export type { KarniProviderProps } from "./schema/provider";

export { useSchema } from "./schema/useSchema";
export type { UseSchemaResult } from "./schema/useSchema";

export { zodFor } from "./schema/zod";
export type {
  FieldKind,
  RelationRef,
  FieldDef,
  OperationDef,
  ResourceSchema,
} from "./schema/types";

// auth
export { AuthProvider, useAuth } from "./auth/provider";
export type { AuthProviderProps, AuthContextValue } from "./auth/provider";

export { AuthGuard, defaultAuthGuardSlots } from "./auth/AuthGuard";
export type {
  AuthGuardProps,
  AuthGuardSlots,
  AuthGuardAnonymousProps,
  AuthGuardDeniedProps,
} from "./auth/AuthGuard";

export { LoginForm, defaultLoginFormSlots } from "./auth/LoginForm";
export type { LoginFormProps, LoginFormSlots, LoginFormErrorProps } from "./auth/LoginForm";

export { usePermission } from "./auth/usePermission";
export type { PermissionHelpers } from "./auth/usePermission";

export { createLocalStorageTokenStorage, createMemoryTokenStorage } from "./auth/storage";
export type { TokenStorage } from "./auth/storage";

export type { KarniUser, AuthStatus, LoginResult } from "./auth/types";

// support components
export { Page, defaultPageSlots } from "./components/page/page";
export type {
  PageProps,
  PageSlots,
  PageHeaderProps,
  PageSlotContentProps,
} from "./components/page/page";

export { Layout, defaultLayoutSlots } from "./components/layout/layout";
export type {
  LayoutProps,
  LayoutNavItem,
  LayoutSlots,
  LayoutHeaderProps,
  LayoutSidebarProps,
  LayoutNavLinkProps,
  LayoutMobileDrawerProps,
  LayoutSkipLinkProps,
} from "./components/layout/layout";

export { KarniMark } from "./components/brand/karni-mark";
export type { KarniMarkProps } from "./components/brand/karni-mark";

export {
  Modal,
  ModalClose,
  ModalTitle,
  ModalDescription,
  defaultModalSlots,
} from "./components/modal/modal";
export type {
  ModalProps,
  ModalSlots,
  ModalHeaderProps,
  ModalFooterProps,
  ModalCloseButtonProps,
} from "./components/modal/modal";

export { Toaster, toastVariants, defaultToasterSlots } from "./components/toast/toaster";
export type {
  ToasterProps,
  ToastVariantProps,
  ToasterSlots,
  ToasterSlotProps,
  ToasterCloseButtonProps,
} from "./components/toast/toaster";
export { useToast } from "./components/toast/use-toast";
export type { UseToastResult } from "./components/toast/use-toast";
export type {
  ToastHandle,
  ToastInstance,
  ToastOptions,
  ToastVariant,
} from "./components/toast/toast-store";

export { EmptyState, defaultEmptyStateSlots } from "./components/empty-state/empty-state";
export type {
  EmptyStateProps,
  EmptyStateSlots,
  EmptyStateSlotProps,
} from "./components/empty-state/empty-state";
export { FileUpload, defaultFileUploadSlots } from "./components/file-upload/FileUpload";
export type {
  FileUploadProps,
  FileUploadRejectReason,
  FileUploadSlots,
  FileUploadDropzoneProps,
  FileUploadFileRowProps,
} from "./components/file-upload/FileUpload";

export { Stat, defaultStatSlots } from "./components/stat/stat";
export type { StatProps, StatSlots, StatSlotProps, StatDeltaProps } from "./components/stat/stat";

export { DataChart, defaultDataChartSlots } from "./components/chart/data-chart";
export type {
  DataChartProps,
  DataChartKind,
  DataChartPoint,
  DataChartSeries,
  DataChartTooltipContext,
  DataChartSlots,
  DataChartTooltipProps,
  DataChartLegendProps,
  DataChartEmptyProps,
  DataChartLoadingProps,
} from "./components/chart/data-chart";
