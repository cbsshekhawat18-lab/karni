/**
 * Experimental. How a protected file field (`x-karni-storage` with `protected:
 * true`) is shown by ResourceDetail and ResourceTable. @karni/ui knows nothing
 * of buckets or signed links: the storage module's package (@karni/storage-ui)
 * registers its `ProtectedFileLink` when it is imported, and the screens then
 * render every protected file field with it, from the schema. Without one a
 * protected field is a plain link, as any file field.
 */
import * as React from "react";
import type { FieldDef } from "../../schema/types";

/** What a registered protected-file link receives. */
export interface ProtectedFileLinkRenderProps {
  /** The field's value as the API gives it: the download path. */
  href: string;
  className?: string;
  children?: React.ReactNode;
}

let registered: React.ComponentType<ProtectedFileLinkRenderProps> | null = null;

/**
 * Experimental. Sets the component that shows a protected file field. Called by
 * @karni/storage-ui when it is imported. A project may call it with its own link
 * (e.g. one that opens the file in a viewer). Pass `null` to remove it.
 */
export function registerProtectedFileLink(
  component: React.ComponentType<ProtectedFileLinkRenderProps> | null,
): void {
  registered = component;
}

/** The registered component for `field`, or null when the field is not protected or none is registered. */
export function protectedFileLinkFor(
  field: FieldDef,
): React.ComponentType<ProtectedFileLinkRenderProps> | null {
  return field.protected === true ? registered : null;
}
