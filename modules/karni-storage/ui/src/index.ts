/**
 * @karni/storage-ui public barrel: protected files of the karni_storage
 * module (`karni add storage`). Explicit exports only. Importing the package
 * registers its component roles when @karni/ui has the registry (G8).
 *
 * Experimental: every name here may change in a minor release, with a
 * CHANGELOG entry.
 */
import { registerStorageRoles } from "./roles";

export { ProtectedFileInput } from "./ProtectedFileInput";
export type { ProtectedFileInputOptions } from "./ProtectedFileInput";

export { ProtectedFileLink, ProtectedImage } from "./ProtectedFileLink";
export type { ProtectedFileLinkProps, ProtectedImageProps } from "./ProtectedFileLink";

export { uploadReference, useProtectedFileLink, useProtectedUpload } from "./hooks";
export type {
  ProtectedUploadStatus,
  UseProtectedFileLinkOptions,
  UseProtectedUploadOptions,
  UseProtectedUploadResult,
} from "./hooks";

export { BucketUploadError, xhrTransport } from "./transport";
export type { BucketRequest, BucketTransport } from "./transport";

export { UPLOAD_REFERENCE_TYPE } from "./types";
export type {
  ConfirmAnswer,
  FileLink,
  ProtectedUploadResult,
  UploadAnswer,
  UploadMethod,
} from "./types";

export { STORAGE_COMPONENT_ROLES, registerStorageRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";

registerStorageRoles();
