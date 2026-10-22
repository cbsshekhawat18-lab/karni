/**
 * Barrel-facing path for <ResourceForm>. The implementation lives in
 * ./form/ (resource form builder); every contract-pinned export name is
 * re-exported here so src/index.ts keeps resolving this module.
 */
export { ResourceForm, defaultResourceFormSlots } from "./form/ResourceForm";
export type {
  ResourceFormProps,
  ResourceFormSlots,
  FieldOverride,
  KarniFieldProps,
} from "./form/ResourceForm";
export type {
  ResourceFormErrorSummaryProps,
  ResourceFormFieldError,
  ResourceFormForbiddenProps,
  ResourceFormLoadingProps,
  ResourceFormSubmitErrorProps,
} from "./form/form-states";
