/**
 * @karni/ui public barrel.
 *
 * Every public name of the package is re-exported here, explicitly, so that
 * scripts/generate-manifest.mjs can parse this file and emit dist/manifest.json
 * (contract D7). Keep exports in the explicit `export { ... } from` /
 * `export type { ... } from` form — no `export *`.
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

export { ResourceForm } from "./components/resource/ResourceForm";
export type {
  ResourceFormProps,
  FieldOverride,
  KarniFieldProps,
} from "./components/resource/ResourceForm";

export { ResourceDetail } from "./components/resource/ResourceDetail";
export type {
  ResourceDetailProps,
  ResourceDetailFieldOverride,
} from "./components/resource/ResourceDetail";

export { ResourceSelect } from "./components/resource/ResourceSelect";
export type { ResourceSelectProps } from "./components/resource/ResourceSelect";

export { ChangeHistory } from "./components/resource/history/ChangeHistory";
export type { ChangeHistoryProps } from "./components/resource/history/ChangeHistory";
export { useChangeHistory, changeHistoryKey } from "./hooks/useChangeHistory";
export type {
  ChangeAction,
  ChangeLogEntry,
  ChangeHistoryPage,
  ChangeHistoryParams,
} from "./hooks/useChangeHistory";

export { ResourceImport } from "./components/resource/import/ResourceImport";
export type { ResourceImportProps } from "./components/resource/import/ResourceImport";
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

export { AuthGuard } from "./auth/AuthGuard";
export type { AuthGuardProps } from "./auth/AuthGuard";

export { LoginForm } from "./auth/LoginForm";
export type { LoginFormProps } from "./auth/LoginForm";

export { usePermission } from "./auth/usePermission";
export type { PermissionHelpers } from "./auth/usePermission";

export { createLocalStorageTokenStorage, createMemoryTokenStorage } from "./auth/storage";
export type { TokenStorage } from "./auth/storage";

export type { KarniUser, AuthStatus, LoginResult } from "./auth/types";

// support components
export { Page } from "./components/page/page";
export type { PageProps } from "./components/page/page";

export { Layout } from "./components/layout/layout";
export type { LayoutProps, LayoutNavItem } from "./components/layout/layout";

export { KarniMark } from "./components/brand/karni-mark";
export type { KarniMarkProps } from "./components/brand/karni-mark";

export { Modal, ModalClose } from "./components/modal/modal";
export type { ModalProps } from "./components/modal/modal";

export { Toaster, toastVariants } from "./components/toast/toaster";
export type { ToasterProps, ToastVariantProps } from "./components/toast/toaster";
export { useToast } from "./components/toast/use-toast";
export type { UseToastResult } from "./components/toast/use-toast";
export type {
  ToastHandle,
  ToastInstance,
  ToastOptions,
  ToastVariant,
} from "./components/toast/toast-store";

export { EmptyState } from "./components/empty-state/empty-state";
export type { EmptyStateProps } from "./components/empty-state/empty-state";
export { FileUpload } from "./components/file-upload/FileUpload";
export type { FileUploadProps, FileUploadRejectReason } from "./components/file-upload/FileUpload";

export { Stat } from "./components/stat/stat";
export type { StatProps } from "./components/stat/stat";

export { DataChart } from "./components/chart/data-chart";
export type {
  DataChartProps,
  DataChartKind,
  DataChartPoint,
  DataChartSeries,
  DataChartTooltipContext,
} from "./components/chart/data-chart";
