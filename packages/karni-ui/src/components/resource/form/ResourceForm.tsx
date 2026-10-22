import { zodResolver } from "@hookform/resolvers/zod";
import * as React from "react";
import { FormProvider, useForm } from "react-hook-form";
import type {
  Control,
  FieldError,
  FieldErrors,
  FieldValues,
  Mode,
  Resolver,
  UseFormReturn,
} from "react-hook-form";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import { useUnsavedChangesGuard } from "../../../hooks/useUnsavedChangesGuard";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import type { FieldDef, ResourceSchema } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { zodFor } from "../../../schema/zod";
import { describeError, type KarniErrorContext } from "../../../states/describe-error";
import type { ErrorSlotProps } from "../../../states/ErrorState";
import { PendingButton } from "../../../states/PendingButton";
import { AlertIcon } from "../../primitives/icons";
import { Label } from "../../primitives/label";
import { resourceNames, type ResourceLabel, type ResourceNames } from "../resource-names";
import { DefaultFieldControl, KINDS_WITHOUT_ARIA_REQUIRED } from "./field-inputs";
import {
  FIELD_GAP,
  ResourceFormErrorSummary,
  ResourceFormForbidden,
  ResourceFormLoadError,
  ResourceFormSkeleton,
  ResourceFormSubmitError,
  SUBMIT_ROW,
  type ResourceFormErrorSummaryProps,
  type ResourceFormFieldError,
  type ResourceFormForbiddenProps,
  type ResourceFormLoadingProps,
  type ResourceFormSubmitErrorProps,
} from "./form-states";
import { buildFormValues, humanizeValue, prepareSubmit } from "./prepare";
import { mapServerErrors } from "./server-errors";

registerComponentRole("resource-form", "ResourceForm");

/** Props passed to a custom field component (the `fields` escape hatch). */
export interface KarniFieldProps {
  field: FieldDef;
  name: string;
  label: string;
  required: boolean;
  control: Control<FieldValues>;
  error?: string;
  disabled?: boolean;
  /** Pass-through from FieldOverride.props. */
  props?: Record<string, unknown>;
}

export interface FieldOverride {
  component?: React.ComponentType<KarniFieldProps>;
  label?: string;
  hidden?: boolean;
  props?: Record<string, unknown>;
}

/**
 * The replaceable parts of ResourceForm (`slots`). Each default is in
 * `defaultResourceFormSlots`.
 */
export interface ResourceFormSlots {
  /** While the schema or the edited row loads. */
  Loading: React.ComponentType<ResourceFormLoadingProps>;
  /** A failed load of the schema or the row, with retry when it can help. */
  Error: React.ComponentType<ErrorSlotProps>;
  /** A 403 while loading the row: the role cannot edit it. */
  Forbidden: React.ComponentType<ResourceFormForbiddenProps>;
  /** After a failed submit with more than one problem: every one, each field focusable. */
  ErrorSummary: React.ComponentType<ResourceFormErrorSummaryProps>;
  /** A submit that failed for a reason other than the values (offline, 403, 409, 5xx). */
  SubmitError: React.ComponentType<ResourceFormSubmitErrorProps>;
}

/** ResourceForm's own slot components, for wrapping rather than rewriting. */
export const defaultResourceFormSlots: ResourceFormSlots = {
  Loading: ResourceFormSkeleton,
  Error: ResourceFormLoadError,
  Forbidden: ResourceFormForbidden,
  ErrorSummary: ResourceFormErrorSummary,
  SubmitError: ResourceFormSubmitError,
};

export interface ResourceFormProps {
  resource: string;
  /** Present → edit mode: loads the UNEXPANDED item, PATCHes dirty fields only (D10). */
  id?: string | number;
  defaultValues?: Record<string, unknown>;
  onSuccess?: (result: Record<string, unknown>) => void;
  /** Called with every failed submit's error (the form shows it as well). */
  onError?: (error: unknown) => void;
  fields?: Record<string, FieldOverride>;
  /** Custom RHF-registered nodes appended after the derived fields. */
  extraFields?: React.ReactNode;
  transformSubmit?: (values: Record<string, unknown>) => Record<string, unknown>;
  /** Replaces the submit row. */
  actions?: React.ReactNode;
  /** The submit button's text. Default "Create" or "Save changes". */
  submitLabel?: React.ReactNode;
  className?: string;
  /** Replaces parts of the form: loading, load error, permission, error summary, submit error. */
  slots?: Partial<ResourceFormSlots>;
  /**
   * When a field first validates (react-hook-form's `mode`). Default "onBlur":
   * a field is checked when the user leaves it, never on every keystroke.
   */
  validationMode?: Mode;
  /**
   * When a field validates again after a submit (react-hook-form's
   * `reValidateMode`). Default "onBlur". Independently of both, a field that
   * shows an error re-validates on every change, so the error clears as soon
   * as the value is fixed.
   */
  reValidateMode?: Exclude<Mode, "onTouched" | "all">;
  /** Focus the first field when the form appears. Default: true to create, false to edit. */
  autoFocus?: boolean;
  /**
   * Warn before the page unloads with unsaved changes (`beforeunload`).
   * Default true. Pass false to opt out. In-app navigation: see `onDirtyChange`.
   */
  guardUnsavedChanges?: boolean;
  /**
   * Called when the form gains or loses unsaved changes, and with false just
   * before `onSuccess`. Feed it to `useUnsavedChangesGuard().setDirty` and
   * the router's blocker to stop in-app navigation away from a dirty form.
   */
  onDirtyChange?: (dirty: boolean) => void;
  /**
   * How the resource is named in messages. The default is derived from
   * `resource` ("events" → "event").
   */
  resourceLabel?: ResourceLabel;
}

/** Field kinds the generic form knows how to render (others need an override). */
const EDITABLE_KINDS: ReadonlySet<string> = new Set([
  "string",
  "text",
  "number",
  "integer",
  "boolean",
  "date",
  "datetime",
  "enum",
  "relation",
  "file",
  "json",
]);

/**
 * The fields the form submits: writable, of a kind it can render (or with a
 * custom component). Fields the role cannot see are absent from its schema
 * and fields it cannot write are read-only there, so neither is ever here.
 */
function writableFields(
  schema: ResourceSchema,
  overrides: Record<string, FieldOverride> | undefined,
): FieldDef[] {
  return schema.fields.filter(
    (field) =>
      !field.readOnly &&
      (EDITABLE_KINDS.has(field.kind) || overrides?.[field.name]?.component !== undefined),
  );
}

/** The fields the form shows: writable and not hidden, labels overridden. */
function shownFields(
  fields: readonly FieldDef[],
  overrides: Record<string, FieldOverride> | undefined,
): FieldDef[] {
  return fields
    .filter((field) => overrides?.[field.name]?.hidden !== true)
    .map((field) => {
      const label = overrides?.[field.name]?.label;
      return label !== undefined ? { ...field, label } : field;
    });
}

/** A rejected request as DRF answered it: the status and the parsed body. */
function apiFailure(error: unknown): { status: number; data: unknown } | null {
  if (typeof error !== "object" || error === null) return null;
  const candidate = error as { status?: unknown; data?: unknown };
  return typeof candidate.status === "number"
    ? { status: candidate.status, data: candidate.data }
    : null;
}

/** zod issue codes that, on an empty value, only mean "nothing was entered". */
const TYPE_ISSUES: ReadonlySet<string> = new Set([
  "invalid_type",
  "invalid_enum_value",
  "invalid_union",
  "invalid_literal",
]);

function isEmptyValue(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

function hasValueAt(values: FieldValues, path: string): boolean {
  let current: unknown = values;
  for (const segment of path.split(".")) {
    if (typeof current !== "object" || current === null) return false;
    current = (current as Record<string, unknown>)[segment];
  }
  return current !== undefined;
}

function errorAt(errors: FieldErrors<FieldValues>, path: string): FieldError | undefined {
  let current: unknown = errors;
  for (const segment of path.split(".")) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  const entry = current as FieldError | undefined;
  return typeof entry?.message === "string" ? entry : undefined;
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

interface FormFieldRowProps {
  field: FieldDef;
  inputId: string;
  override?: FieldOverride;
  control: Control<FieldValues>;
  error?: string;
  disabled?: boolean;
}

function FormFieldRow({
  field,
  inputId,
  override,
  control,
  error,
  disabled,
}: FormFieldRowProps): React.ReactElement {
  if (override?.component !== undefined) {
    const Component = override.component;
    return (
      <Component
        field={field}
        name={field.name}
        label={field.label}
        required={field.required}
        control={control}
        error={error}
        disabled={disabled}
        props={override.props}
      />
    );
  }

  const labelId = `${inputId}-label`;
  const errorId = `${inputId}-error`;
  const descriptionId = `${inputId}-description`;
  const describedBy =
    [field.description !== undefined ? descriptionId : null, error !== undefined ? errorId : null]
      .filter((part): part is string => part !== null)
      .join(" ") || undefined;
  // A switch is never empty, so "required" would only mislead.
  const required = field.required && field.kind !== "boolean";

  return (
    <div className={FIELD_GAP} data-karni-field={field.name}>
      <Label htmlFor={inputId} id={labelId}>
        {field.label}
        {required ? (
          <span aria-hidden="true" className="text-destructive">
            {" *"}
          </span>
        ) : null}
        {required && KINDS_WITHOUT_ARIA_REQUIRED.has(field.kind) ? (
          <span className="sr-only"> (required)</span>
        ) : null}
      </Label>
      <DefaultFieldControl
        field={field}
        control={control}
        inputId={inputId}
        labelId={labelId}
        describedBy={describedBy}
        invalid={error !== undefined}
        required={required}
        disabled={disabled}
        inputProps={override?.props}
      />
      {field.description !== undefined ? (
        <p id={descriptionId} className="text-sm text-muted-foreground">
          {field.description}
        </p>
      ) : null}
      {error !== undefined ? (
        <p id={errorId} className="flex items-start gap-1.5 text-sm font-medium text-foreground">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          {error}
        </p>
      ) : null}
    </div>
  );
}

type PendingFocus =
  | { kind: "field"; name: string }
  | { kind: "summary" }
  | { kind: "banner" }
  | { kind: "restore"; element: HTMLElement | null };

interface ResourceFormInnerProps extends ResourceFormProps {
  schema: ResourceSchema;
  item?: Record<string, unknown>;
  names: ResourceNames;
  slotsResolved: ResourceFormSlots;
  reloadItem?: () => Promise<unknown>;
}

function ResourceFormInner(props: ResourceFormInnerProps): React.ReactElement {
  const {
    resource,
    id,
    defaultValues,
    onSuccess,
    onError,
    fields: fieldOverrides,
    extraFields,
    transformSubmit,
    actions,
    submitLabel,
    className,
    schema,
    item,
    names,
    slotsResolved: slots,
    validationMode = "onBlur",
    reValidateMode = "onBlur",
    autoFocus,
    guardUnsavedChanges = true,
    onDirtyChange,
    reloadItem,
  } = props;
  const mode = id === undefined ? "create" : "update";
  const mutations = useResourceMutations(resource);
  const baseId = React.useId();
  const inputIdOf = React.useCallback((name: string) => `${baseId}-${name}`, [baseId]);

  const formFields = React.useMemo(
    () => writableFields(schema, fieldOverrides),
    [schema, fieldOverrides],
  );
  const visibleFields = React.useMemo(
    () => shownFields(formFields, fieldOverrides),
    [formFields, fieldOverrides],
  );

  const initialValues = React.useMemo(
    () => buildFormValues({ fields: formFields, item, defaultValues }),
    [formFields, item, defaultValues],
  );

  const resolver = React.useMemo<Resolver<FieldValues>>(() => {
    const base = zodResolver(zodFor(schema, mode)) as unknown as Resolver<FieldValues>;
    // A cleared optional, non-nullable field (a select's "no selection") is
    // omitted from the request (D3), so it must not fail validation as null.
    // Many relations are cleared with [] and stay.
    const omittable = new Set(
      schema.fields
        .filter(
          (field) =>
            !field.required &&
            !field.nullable &&
            !(field.kind === "relation" && field.relation?.many === true),
        )
        .map((field) => field.name),
    );
    const required = new Set(
      schema.fields.filter((field) => field.required).map((field) => field.name),
    );
    // An optional text field left empty is not an invalid email or URL: its
    // format is checked only when something was typed. The "" itself is kept
    // in the submitted values (clearing a field in edit mode must save).
    const optionalText = new Set(
      schema.fields
        .filter((field) => !field.required && (field.kind === "string" || field.kind === "text"))
        .map((field) => field.name),
    );
    return async (values, context, options) => {
      const blank = Object.keys(values).filter(
        (name) => values[name] === "" && optionalText.has(name),
      );
      const cleaned: FieldValues = Object.fromEntries(
        Object.entries(values).filter(
          ([name, value]) =>
            !(value === null && omittable.has(name)) && !(value === "" && optionalText.has(name)),
        ),
      );
      const result = await base(cleaned, context, options);
      if (Object.keys(result.errors).length === 0) {
        for (const name of blank) (result.values as FieldValues)[name] = "";
      }
      // An empty required field reads "This field is required.", not zod's
      // "Expected 'draft' | 'published', received null" (its own messages stay).
      for (const [name, entry] of Object.entries(result.errors)) {
        const error = entry as FieldError | undefined;
        if (
          error !== undefined &&
          required.has(name) &&
          isEmptyValue(values[name]) &&
          TYPE_ISSUES.has(String(error.type))
        ) {
          error.message = "This field is required.";
        }
      }
      return result;
    };
  }, [schema, mode]);

  const methods: UseFormReturn<FieldValues> = useForm<FieldValues>({
    resolver,
    values: initialValues,
    resetOptions: { keepDirtyValues: true },
    mode: validationMode,
    reValidateMode,
    shouldFocusError: false,
  });

  const { formState } = methods;
  const submitting =
    formState.isSubmitting || mutations.create.isPending || mutations.update.isPending;

  // --- unsaved changes ---------------------------------------------------
  /**
   * Set by a successful save until the form has been reset (which happens
   * once the submit has settled): saved values are never "unsaved".
   */
  const savedRef = React.useRef<"create" | "update" | null>(null);
  const dirty = formState.isDirty && savedRef.current === null;
  const guard = useUnsavedChangesGuard({ dirty, enabled: guardUnsavedChanges });
  const onDirtyChangeRef = React.useRef(onDirtyChange);
  onDirtyChangeRef.current = onDirtyChange;
  React.useEffect(() => {
    onDirtyChangeRef.current?.(dirty);
  }, [dirty]);

  // --- submit outcome state ----------------------------------------------
  const [submitError, setSubmitError] = React.useState<unknown>(null);
  const [rootMessages, setRootMessages] = React.useState<readonly string[]>([]);
  const [summaryShown, setSummaryShown] = React.useState(false);
  const [reloading, setReloading] = React.useState(false);
  const [announcement, setAnnouncement] = React.useState("");
  const pendingFocus = React.useRef<PendingFocus | null>(null);
  const [focusTick, setFocusTick] = React.useState(0);
  const summaryRef = React.useRef<HTMLDivElement>(null);
  const bannerRef = React.useRef<HTMLDivElement>(null);
  const formRef = React.useRef<HTMLFormElement>(null);
  const inFlight = React.useRef(false);
  /** What had focus when the submit started, to give it back after a save. */
  const submitOrigin = React.useRef<HTMLElement | null>(null);

  const requestFocus = (target: PendingFocus): void => {
    pendingFocus.current = target;
    setFocusTick((tick) => tick + 1);
  };

  const labelOf = React.useCallback(
    (path: string): string =>
      visibleFields.find((field) => field.name === path)?.label ??
      humanizeValue(path.replace(/\./g, " ")),
    [visibleFields],
  );

  const focusField = React.useCallback(
    (name: string): void => {
      methods.setFocus(name);
      const element = document.getElementById(inputIdOf(name));
      if (element !== null && document.activeElement !== element) element.focus();
    },
    [methods, inputIdOf],
  );

  // Field errors in the order the fields appear, then extra fields.
  const fieldErrors: ResourceFormFieldError[] = [];
  for (const field of visibleFields) {
    const entry = errorAt(formState.errors, field.name);
    if (entry?.message !== undefined) {
      fieldErrors.push({
        name: field.name,
        label: field.label,
        message: entry.message,
        focus: () => focusField(field.name),
        href: `#${inputIdOf(field.name)}`,
      });
    }
  }
  for (const [name, entry] of Object.entries(formState.errors)) {
    if (name === "root" || visibleFields.some((field) => field.name === name)) continue;
    const message = (entry as FieldError | undefined)?.message;
    if (typeof message === "string") {
      fieldErrors.push({
        name,
        label: labelOf(name),
        message,
        focus: () => focusField(name),
        href: `#${inputIdOf(name)}`,
      });
    }
  }
  const problemCount = fieldErrors.length + rootMessages.length;

  const action = mode === "create" ? "create" : "save";
  const errorContext: KarniErrorContext =
    mode === "create"
      ? { action: "create", resource: names.plural }
      : { action: "save", resource: `this ${names.singular}` };

  /** After a submit the values failed: the summary when more than one thing is wrong, else the field. */
  const afterFailedValidation = (
    failing: ReadonlyArray<{ name: string; message: string }>,
    roots: readonly string[],
  ): void => {
    setSubmitError(null);
    if (failing.length + roots.length > 1 || roots.length > 0) {
      setSummaryShown(true);
      setAnnouncement("");
      requestFocus({ kind: "summary" });
      return;
    }
    const only = failing[0];
    if (only === undefined) return;
    setSummaryShown(false);
    setAnnouncement(`${labelOf(only.name)}: ${only.message}`);
    requestFocus({ kind: "field", name: only.name });
  };

  /** The failing fields in the order the form shows them, extra fields last. */
  const failingFields = (
    errors: FieldErrors<FieldValues>,
  ): Array<{ name: string; message: string }> => {
    const shown = visibleFields.map((field) => field.name);
    const extra = Object.keys(errors).filter((name) => name !== "root" && !shown.includes(name));
    return [...shown, ...extra].flatMap((name) => {
      const message = errorAt(errors, name)?.message;
      return message !== undefined ? [{ name, message }] : [];
    });
  };

  const applyServerFailure = (error: unknown, raw: FieldValues): boolean => {
    const failure = apiFailure(error);
    if (failure === null || (failure.status !== 400 && failure.status !== 422)) return false;
    const shownNames = new Set(visibleFields.map((field) => field.name));
    const schemaNames = new Set(schema.fields.map((field) => field.name));
    const mapped = mapServerErrors(failure.data, {
      isField: (path) =>
        shownNames.has(path) || (!schemaNames.has(path.split(".")[0]) && hasValueAt(raw, path)),
      labelOf,
    });
    const names = Object.keys(mapped.fields);
    if (names.length === 0 && mapped.root.length === 0) return false;
    for (const [name, message] of Object.entries(mapped.fields)) {
      methods.setError(name, { type: "server", message });
    }
    if (mapped.root.length > 0) {
      // Kept on `root.server` too, for extraFields that read formState.
      methods.setError("root.server", { type: "server", message: mapped.root.join(" ") });
    }
    setRootMessages(mapped.root);
    const failing = [
      ...visibleFields.map((field) => field.name).filter((name) => names.includes(name)),
      ...names.filter((name) => !shownNames.has(name)),
    ].map((name) => ({ name, message: mapped.fields[name] ?? "" }));
    afterFailedValidation(failing, mapped.root);
    return true;
  };

  const submit = methods.handleSubmit(
    async (raw) => {
      setRootMessages([]);
      methods.clearErrors("root.server");
      const { values, jsonErrors } = prepareSubmit({
        fields: formFields,
        raw,
        mode,
        dirtyFields: methods.formState.dirtyFields,
      });
      if (jsonErrors.length > 0) {
        for (const jsonError of jsonErrors) {
          methods.setError(jsonError.name, { type: "validate", message: jsonError.message });
        }
        afterFailedValidation(jsonErrors, []);
        return;
      }
      const payload = transformSubmit !== undefined ? transformSubmit(values) : values;
      let result: Record<string, unknown>;
      try {
        result =
          id === undefined
            ? await mutations.create.mutateAsync(payload)
            : await mutations.update.mutateAsync({ id, values: payload });
      } catch (error) {
        // The typed values stay: nothing below resets the form.
        if (!applyServerFailure(error, raw)) {
          setSummaryShown(false);
          setSubmitError(error);
          requestFocus({ kind: "banner" });
        }
        onError?.(error);
        return;
      }
      setSummaryShown(false);
      setSubmitError(null);
      // Clean before onSuccess, so a navigation made there is not blocked.
      // The form itself resets once the submit has settled (below):
      // react-hook-form's Controllers re-register stale values when reset
      // runs inside the submit handler.
      savedRef.current = mode;
      guard.setDirty(false);
      onDirtyChangeRef.current?.(false);
      setAnnouncement(mode === "create" ? `${humanizeValue(names.singular)} created.` : "Saved.");
      requestFocus({ kind: "restore", element: submitOrigin.current });
      onSuccess?.(result);
    },
    (errors) => {
      setRootMessages([]);
      methods.clearErrors("root.server");
      afterFailedValidation(failingFields(errors), []);
    },
  );

  // One submit at a time, whatever starts it (button, Enter, Ctrl+Enter, "Try again").
  const runSubmit = (): void => {
    if (inFlight.current) return;
    inFlight.current = true;
    submitOrigin.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void submit().finally(() => {
      inFlight.current = false;
    });
  };

  // After a save, once the submit has settled: create starts over from the
  // initial values; edit makes the saved values the new baseline, so it is
  // clean at once (the refetched row then replaces them). keepDirtyValues is
  // switched off explicitly: reset() otherwise inherits the form's
  // resetOptions and would keep every typed value.
  React.useEffect(() => {
    const saved = savedRef.current;
    if (saved === null || submitting) return;
    if (saved === "create") methods.reset(initialValues, { keepDirtyValues: false });
    else methods.reset(methods.getValues(), { keepDirtyValues: false });
    savedRef.current = null;
  }, [focusTick, submitting, methods, initialValues]);

  // Focus moves once the submit has settled and the fields are enabled again.
  React.useEffect(() => {
    const target = pendingFocus.current;
    if (target === null || submitting) return;
    pendingFocus.current = null;
    switch (target.kind) {
      case "field":
        focusField(target.name);
        break;
      case "summary":
        summaryRef.current?.focus();
        break;
      case "banner":
        bannerRef.current?.focus();
        break;
      case "restore":
        if (
          target.element !== null &&
          target.element.isConnected &&
          (document.activeElement === null || document.activeElement === document.body)
        ) {
          target.element.focus();
        }
        break;
    }
  }, [focusTick, submitting, focusField]);

  // The summary goes once every problem is fixed.
  React.useEffect(() => {
    if (summaryShown && problemCount === 0) setSummaryShown(false);
  }, [summaryShown, problemCount]);

  // A field that gains an error when it loses focus is announced (the summary announces itself).
  const errorSignature = fieldErrors.map((entry) => `${entry.name}:${entry.message}`).join("|");
  const previousErrors = React.useRef<ReadonlySet<string>>(new Set());
  React.useEffect(() => {
    const current = new Set(fieldErrors.map((entry) => entry.name ?? ""));
    const fresh = fieldErrors.find((entry) => !previousErrors.current.has(entry.name ?? ""));
    previousErrors.current = current;
    if (fresh !== undefined && !summaryShown) {
      setAnnouncement(`${fresh.label}: ${fresh.message}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the error text, not the array identity
  }, [errorSignature]);

  // Autofocus: the first field, on create (or when asked).
  const shouldAutoFocus = autoFocus ?? mode === "create";
  const autoFocusTarget = visibleFields[0]?.name;
  React.useEffect(() => {
    if (shouldAutoFocus && autoFocusTarget !== undefined) focusField(autoFocusTarget);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the form appears
  }, []);

  const reload =
    reloadItem !== undefined
      ? () => {
          setReloading(true);
          void reloadItem().finally(() => {
            setReloading(false);
            setSubmitError(null);
          });
        }
      : undefined;

  const handleKeyDownCapture = (event: React.KeyboardEvent<HTMLFormElement>): void => {
    // Ctrl/Cmd+Enter submits from any control, a textarea or an open list included.
    if (
      event.key === "Enter" &&
      (event.metaKey || event.ctrlKey) &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.stopPropagation();
      runSubmit();
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLFormElement>): void => {
    // Plain Enter in a one-line input submits natively through the submit
    // button; with `actions` that have none, submit here instead.
    if (event.key !== "Enter" || event.defaultPrevented || event.nativeEvent.isComposing) return;
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (["checkbox", "radio", "file", "button", "submit", "reset"].includes(target.type)) return;
    if (formRef.current?.querySelector("[type='submit']:not(:disabled)") != null) return;
    event.preventDefault();
    runSubmit();
  };

  const fieldError = (name: string): string | undefined => errorAt(formState.errors, name)?.message;

  const SubmitErrorSlot = slots.SubmitError;
  const SummarySlot = slots.ErrorSummary;
  const summaryTitle =
    fieldErrors.length > 0
      ? `${fieldErrors.length} ${plural(fieldErrors.length, "field needs", "fields need")} attention`
      : `Couldn't ${action} ${mode === "create" ? names.singular : `this ${names.singular}`}`;

  return (
    <FormProvider {...methods}>
      <form
        ref={formRef}
        onSubmit={(event) => {
          event.preventDefault();
          runSubmit();
        }}
        onKeyDownCapture={handleKeyDownCapture}
        onKeyDown={handleKeyDown}
        noValidate
        aria-busy={submitting || undefined}
        className={cn("space-y-5", className)}
      >
        {submitError !== null ? (
          <div ref={bannerRef} tabIndex={-1} className="rounded-md outline-none">
            <SubmitErrorSlot
              error={submitError}
              context={errorContext}
              onRetry={runSubmit}
              retrying={submitting}
              onReload={reload}
              reloading={reloading}
            />
          </div>
        ) : null}
        {summaryShown && problemCount > 0 ? (
          <div ref={summaryRef} tabIndex={-1} className="rounded-md outline-none">
            <SummarySlot
              title={summaryTitle}
              errors={[...fieldErrors, ...rootMessages.map((message) => ({ message }))]}
            />
          </div>
        ) : null}
        <fieldset disabled={submitting} className="m-0 min-w-0 space-y-5 border-0 p-0">
          {formFields.map((field) => {
            const override = fieldOverrides?.[field.name];
            if (override?.hidden === true) return null;
            const shown = visibleFields.find((candidate) => candidate.name === field.name) ?? field;
            return (
              <FormFieldRow
                key={field.name}
                field={shown}
                inputId={inputIdOf(field.name)}
                override={override}
                control={methods.control}
                error={fieldError(field.name)}
                disabled={submitting}
              />
            );
          })}
          {extraFields}
        </fieldset>
        {actions !== undefined ? (
          actions
        ) : (
          <div className={SUBMIT_ROW}>
            <PendingButton
              type="submit"
              pending={submitting}
              pendingLabel={mode === "create" ? "Creating…" : "Saving…"}
            >
              {submitLabel ?? (mode === "create" ? "Create" : "Save changes")}
            </PendingButton>
          </div>
        )}
        <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {announcement}
        </p>
      </form>
    </FormProvider>
  );
}

/**
 * Schema-driven create and edit form for one resource: inputs, validation and
 * server errors derived from the OpenAPI schema.
 *
 * Contract "ResourceForm" + D2/D3/D10.
 *
 * Create mode POSTs every prepared value. Edit mode loads the UNEXPANDED
 * detail record and PATCHes only dirty fields at top-level granularity, with
 * emptied nullable fields sent as null (D3). Fields validate when they lose
 * focus. A failed submit keeps every typed value, puts DRF's messages on their
 * fields (a summary lists them when more than one fails) and moves focus there.
 * Any other failure (offline, 403, 409, 5xx) is a banner with "Try again" when
 * it can help. Escape hatches: per-field overrides (`fields`), `extraFields`,
 * `transformSubmit`, `actions`, `slots`, `validationMode` / `reValidateMode`
 * and `guardUnsavedChanges` / `onDirtyChange`.
 */
export function ResourceForm(props: ResourceFormProps): React.ReactElement {
  const { resource, id, slots: slotOverrides, resourceLabel, className } = props;
  const slots = React.useMemo(
    () => ({ ...defaultResourceFormSlots, ...slotOverrides }),
    [slotOverrides],
  );
  const names = resourceNames(resource, resourceLabel);
  const schemaResult = useSchema(resource);
  const isEdit = id !== undefined;
  const itemQuery = useResourceItem(resource, id ?? "", undefined, { enabled: isEdit });
  const mode = isEdit ? "update" : "create";

  if (schemaResult.error != null && schemaResult.data === undefined) {
    const ErrorSlot = slots.Error;
    return (
      <div className={className}>
        <ErrorSlot
          error={schemaResult.error}
          context={{ action: "load", resource: "this form" }}
          onRetry={schemaResult.refetch}
          retrying={schemaResult.isFetching}
        />
      </div>
    );
  }
  if (isEdit && itemQuery.error != null && itemQuery.data === undefined) {
    const forbidden =
      describeError(itemQuery.error).kind === "forbidden" ||
      apiFailure(itemQuery.error)?.status === 403;
    if (forbidden) {
      const ForbiddenSlot = slots.Forbidden;
      return (
        <div className={className}>
          <ForbiddenSlot action="edit" resource={`this ${names.singular}`} />
        </div>
      );
    }
    const ErrorSlot = slots.Error;
    return (
      <div className={className}>
        <ErrorSlot
          error={itemQuery.error}
          context={{ action: "load", resource: `this ${names.singular}` }}
          onRetry={() => void itemQuery.refetch()}
          retrying={itemQuery.isFetching}
        />
      </div>
    );
  }
  if (schemaResult.data === undefined || (isEdit && itemQuery.data === undefined)) {
    const LoadingSlot = slots.Loading;
    const fields =
      schemaResult.data !== undefined
        ? shownFields(writableFields(schemaResult.data, props.fields), props.fields)
        : undefined;
    return (
      <div className={className}>
        <LoadingSlot
          fields={fields}
          mode={mode}
          submitLabel={props.submitLabel ?? (isEdit ? "Save changes" : "Create")}
          showSubmitRow={props.actions === undefined}
        />
      </div>
    );
  }
  return (
    <ResourceFormInner
      {...props}
      schema={schemaResult.data}
      item={isEdit ? itemQuery.data : undefined}
      names={names}
      slotsResolved={slots}
      reloadItem={isEdit ? () => itemQuery.refetch() : undefined}
    />
  );
}
