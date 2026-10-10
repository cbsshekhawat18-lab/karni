import { zodResolver } from "@hookform/resolvers/zod";
import * as React from "react";
import { FormProvider, useForm } from "react-hook-form";
import type { Control, FieldValues, Resolver, UseFormReturn } from "react-hook-form";
import { useResourceItem } from "../../../hooks/useResourceItem";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import { cn } from "../../../lib/cn";
import type { FieldDef, ResourceSchema } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { zodFor } from "../../../schema/zod";
import { Button } from "../../primitives/button";
import { Label } from "../../primitives/label";
import { Skeleton } from "../../primitives/skeleton";
import { DefaultFieldControl } from "./field-inputs";
import { buildFormValues, prepareSubmit } from "./prepare";
import { registerComponentRole } from "../../../lib/roles";

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

export interface ResourceFormProps {
  resource: string;
  /** Present → edit mode: loads the UNEXPANDED item, PATCHes dirty fields only (D10). */
  id?: string | number;
  defaultValues?: Record<string, unknown>;
  onSuccess?: (result: Record<string, unknown>) => void;
  onError?: (error: unknown) => void;
  fields?: Record<string, FieldOverride>;
  /** Custom RHF-registered nodes appended after the derived fields. */
  extraFields?: React.ReactNode;
  transformSubmit?: (values: Record<string, unknown>) => Record<string, unknown>;
  /** Replaces the submit row. */
  actions?: React.ReactNode;
  className?: string;
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

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function FormSkeleton({ className }: { className?: string }): React.ReactElement {
  return (
    <div role="status" aria-label="Loading form" className={cn("space-y-5", className)}>
      {[0, 1, 2].map((row) => (
        <div key={row} className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
      <Skeleton className="h-10 w-28" />
    </div>
  );
}

function FormErrorPanel({
  error,
  className,
}: {
  error: unknown;
  className?: string;
}): React.ReactElement {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive",
        className,
      )}
    >
      {errorMessage(error)}
    </div>
  );
}

/**
 * Maps a DRF 400 body ({field: [messages], non_field_errors: [...], detail})
 * onto react-hook-form errors. Unknown keys and non-field messages land on
 * `root.server`.
 */
function applyServerErrors(
  error: unknown,
  knownNames: ReadonlySet<string>,
  methods: UseFormReturn<FieldValues>,
): void {
  if (typeof error !== "object" || error === null) return;
  const maybe = error as { status?: unknown; data?: unknown };
  if (maybe.status !== 400) return;
  const data = maybe.data;
  if (Array.isArray(data)) {
    methods.setError("root.server", { type: "server", message: data.map(String).join(" ") });
    return;
  }
  if (typeof data !== "object" || data === null) return;
  const rootMessages: string[] = [];
  for (const [key, messages] of Object.entries(data as Record<string, unknown>)) {
    const message = Array.isArray(messages) ? messages.map(String).join(" ") : String(messages);
    if (key === "non_field_errors" || key === "detail") {
      rootMessages.push(message);
    } else if (knownNames.has(key)) {
      methods.setError(key, { type: "server", message });
    } else {
      rootMessages.push(`${key}: ${message}`);
    }
  }
  if (rootMessages.length > 0) {
    methods.setError("root.server", { type: "server", message: rootMessages.join(" ") });
  }
}

interface FormFieldRowProps {
  field: FieldDef;
  override?: FieldOverride;
  control: Control<FieldValues>;
  error?: string;
  disabled?: boolean;
}

function FormFieldRow({
  field,
  override,
  control,
  error,
  disabled,
}: FormFieldRowProps): React.ReactElement {
  const inputId = React.useId();
  const label = override?.label ?? field.label;

  if (override?.component !== undefined) {
    const Component = override.component;
    return (
      <Component
        field={field}
        name={field.name}
        label={label}
        required={field.required}
        control={control}
        error={error}
        disabled={disabled}
        props={override.props}
      />
    );
  }

  const errorId = `${inputId}-error`;
  const descriptionId = `${inputId}-description`;
  const describedBy =
    [field.description !== undefined ? descriptionId : null, error !== undefined ? errorId : null]
      .filter((part): part is string => part !== null)
      .join(" ") || undefined;

  return (
    <div className="space-y-2">
      <Label htmlFor={inputId}>
        {label}
        {field.required ? (
          <span aria-hidden="true" className="text-destructive">
            {" *"}
          </span>
        ) : null}
      </Label>
      <DefaultFieldControl
        field={field}
        control={control}
        inputId={inputId}
        describedBy={describedBy}
        invalid={error !== undefined}
        disabled={disabled}
        inputProps={override?.props}
      />
      {field.description !== undefined ? (
        <p id={descriptionId} className="text-sm text-muted-foreground">
          {field.description}
        </p>
      ) : null}
      {error !== undefined ? (
        <p id={errorId} className="text-sm font-medium text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface ResourceFormInnerProps extends ResourceFormProps {
  schema: ResourceSchema;
  item?: Record<string, unknown>;
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
    className,
    schema,
    item,
  } = props;
  const mode = id === undefined ? "create" : "update";
  const mutations = useResourceMutations(resource);

  const formFields = React.useMemo(
    () =>
      schema.fields.filter(
        (field) =>
          !field.readOnly &&
          (EDITABLE_KINDS.has(field.kind) || fieldOverrides?.[field.name]?.component !== undefined),
      ),
    [schema, fieldOverrides],
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
    return (values, context, options) => {
      const cleaned: FieldValues = Object.fromEntries(
        Object.entries(values).filter(([name, value]) => !(value === null && omittable.has(name))),
      );
      return base(cleaned, context, options);
    };
  }, [schema, mode]);

  const methods = useForm<FieldValues>({
    resolver,
    values: initialValues,
    resetOptions: { keepDirtyValues: true },
  });

  const { formState } = methods;
  const submitting =
    formState.isSubmitting || mutations.create.isPending || mutations.update.isPending;

  const onSubmit = methods.handleSubmit(async (raw) => {
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
      return;
    }
    const payload = transformSubmit !== undefined ? transformSubmit(values) : values;
    try {
      const result =
        id === undefined
          ? await mutations.create.mutateAsync(payload)
          : await mutations.update.mutateAsync({ id, values: payload });
      if (id === undefined) {
        methods.reset();
      } else {
        // Keep the (possibly server-normalized) values but clear dirtiness.
        methods.reset(undefined, { keepValues: true });
      }
      onSuccess?.(result);
    } catch (error) {
      const knownNames = new Set([...formFields.map((field) => field.name), ...Object.keys(raw)]);
      applyServerErrors(error, knownNames, methods);
      onError?.(error);
    }
  });

  const rootError = formState.errors.root?.["server"]?.message ?? formState.errors.root?.message;

  const fieldError = (name: string): string | undefined => {
    const entry = formState.errors[name];
    return typeof entry?.message === "string" ? entry.message : undefined;
  };

  return (
    <FormProvider {...methods}>
      <form
        onSubmit={(event) => {
          void onSubmit(event);
        }}
        noValidate
        aria-busy={submitting || undefined}
        className={cn("space-y-5", className)}
      >
        {typeof rootError === "string" ? (
          <div
            role="alert"
            className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {rootError}
          </div>
        ) : null}
        {formFields.map((field) => {
          const override = fieldOverrides?.[field.name];
          if (override?.hidden === true) return null;
          return (
            <FormFieldRow
              key={field.name}
              field={field}
              override={override}
              control={methods.control}
              error={fieldError(field.name)}
              disabled={submitting}
            />
          );
        })}
        {extraFields}
        {actions !== undefined ? (
          actions
        ) : (
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button type="submit" disabled={submitting}>
              {id === undefined ? "Create" : "Save changes"}
            </Button>
          </div>
        )}
      </form>
    </FormProvider>
  );
}

/**
 * Schema-driven create/edit form (contract "ResourceForm" + D2/D3/D10).
 *
 * Create mode POSTs every prepared value; edit mode loads the UNEXPANDED
 * detail record and PATCHes only dirty fields at top-level granularity, with
 * emptied nullable fields sent as null (D3). DRF 400 bodies map onto field
 * errors via setError (non_field_errors → root). Escape hatches: per-field
 * overrides (`fields`), `extraFields`, `transformSubmit` and the `actions`
 * slot.
 */
export function ResourceForm(props: ResourceFormProps): React.ReactElement {
  const { resource, id } = props;
  const schemaResult = useSchema(resource);
  const isEdit = id !== undefined;
  const itemQuery = useResourceItem(resource, id ?? "", undefined, { enabled: isEdit });

  if (schemaResult.error != null) {
    return <FormErrorPanel error={schemaResult.error} className={props.className} />;
  }
  if (isEdit && itemQuery.error != null) {
    return <FormErrorPanel error={itemQuery.error} className={props.className} />;
  }
  if (schemaResult.data === undefined || (isEdit && itemQuery.data === undefined)) {
    return <FormSkeleton className={props.className} />;
  }
  return (
    <ResourceFormInner
      {...props}
      schema={schemaResult.data}
      item={isEdit ? itemQuery.data : undefined}
    />
  );
}
