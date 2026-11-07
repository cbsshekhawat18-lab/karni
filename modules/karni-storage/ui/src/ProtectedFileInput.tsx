/**
 * ProtectedFileInput: a protected file field of `<ResourceForm>`, uploaded
 * straight to the bucket when the user picks the file.
 *
 *     <ResourceForm
 *       resource="products"
 *       fields={{ manual: { component: ProtectedFileInput, props: { resource: "products" } } }}
 *     />
 *
 * It composes @karni/ui's `FileUpload` (its `uploading` state and its error
 * line) and keeps every S3 detail here: @karni/ui knows nothing of buckets.
 * The upload runs as soon as a file is picked, with a progress bar, and the
 * form's value becomes the reference file the server takes
 * (`useProtectedUpload`). On local storage the picked file itself is the
 * value and goes with the form, as for any file field.
 *
 * Experimental: may change in a minor release, with a CHANGELOG entry.
 */
import { FileUpload, Label, cn } from "@karni/ui";
import type { KarniFieldProps } from "@karni/ui";
import * as React from "react";
import { useController } from "react-hook-form";
import { useProtectedUpload } from "./hooks";
import type { BucketTransport } from "./transport";

/** What `FieldOverride.props` may pass to ProtectedFileInput. */
export interface ProtectedFileInputOptions {
  /** The resource's API path, as its viewset is routed: "products". Required. */
  resource?: string;
  /** Same grammar as the native `accept` attribute. The server checks the type too. */
  accept?: string;
  /** Largest file, in bytes, refused before any upload. The server checks it too. */
  maxSize?: number;
  /** Replaces the request to the bucket (see `useProtectedUpload`). */
  transport?: BucketTransport;
  className?: string;
}

function option<T>(props: Record<string, unknown> | undefined, key: string): T | undefined {
  const value = props?.[key];
  return value === undefined ? undefined : (value as T);
}

/** Experimental. A protected file field for `<ResourceForm fields={...}>`. */
export function ProtectedFileInput({
  field,
  name,
  label,
  required,
  control,
  error,
  disabled,
  props,
}: KarniFieldProps): React.ReactElement {
  const resource = option<string>(props, "resource");
  if (resource === undefined || resource === "") {
    throw new Error(
      `ProtectedFileInput for ${name} needs props.resource, the API path of its resource ` +
        '(fields={{ field: { component: ProtectedFileInput, props: { resource: "products" } } }}).',
    );
  }
  const { field: rhf } = useController({ control, name });
  const uploader = useProtectedUpload({
    resource,
    field: name,
    transport: option<BucketTransport>(props, "transport"),
  });
  const [picked, setPicked] = React.useState<File | null>(null);
  const inputId = React.useId();
  const errorId = `${inputId}-error`;

  const change = async (next: File | File[] | null): Promise<void> => {
    const file = Array.isArray(next) ? (next[0] ?? null) : next;
    if (file === null) {
      uploader.reset();
      setPicked(null);
      rhf.onChange(null);
      return;
    }
    setPicked(file);
    try {
      const result = await uploader.upload(file);
      rhf.onChange(result.value);
    } catch {
      setPicked(null);
    }
  };

  const shown = picked ?? (rhf.value as File | string | null | undefined) ?? null;
  const message = uploader.error?.message ?? error;
  return (
    <div
      className={cn("space-y-2", option<string>(props, "className"))}
      data-karni-field={field.name}
    >
      <Label htmlFor={inputId}>
        {label}
        {required ? (
          <span aria-hidden="true" className="text-destructive">
            {" *"}
          </span>
        ) : null}
      </Label>
      <FileUpload
        ref={rhf.ref}
        id={inputId}
        name={rhf.name}
        value={shown}
        onChange={(next) => void change(next)}
        onBlur={rhf.onBlur}
        uploading={uploader.uploading}
        disabled={disabled}
        accept={option<string>(props, "accept")}
        maxSize={option<number>(props, "maxSize")}
        error={message}
        aria-describedby={message !== undefined ? errorId : undefined}
      />
      {uploader.uploading ? (
        <div
          role="progressbar"
          aria-label={`Uploading ${picked?.name ?? "the file"}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(uploader.progress * 100)}
          className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        >
          <div
            className="h-full bg-primary transition-[width]"
            style={{ width: `${Math.round(uploader.progress * 100)}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
