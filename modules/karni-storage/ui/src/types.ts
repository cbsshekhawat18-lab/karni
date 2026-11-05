/**
 * The shapes of the karni_storage endpoints (`karni add storage`).
 *
 * Experimental: these may change in a minor release, with a CHANGELOG entry.
 */

/**
 * Experimental. The content type of a file part that carries a confirmed
 * upload token instead of a file. A row's create or update takes it as the
 * protected field's value, so a form that sends files as multipart passes
 * the token with no change.
 */
export const UPLOAD_REFERENCE_TYPE = "application/vnd.karni.upload";

/** Experimental. How the upload step says the file travels. */
export type UploadMethod = "api" | "post" | "put";

/** Experimental. `POST <resource>/files/<field>/upload/`'s answer. */
export interface UploadAnswer {
  /** "api": local storage, send the file with the row. "post"/"put": send it to `url`. */
  method: UploadMethod;
  max_size: number;
  content_types: string[];
  url?: string;
  /** The presigned POST's form fields (method "post"), sent before the file. */
  fields?: Record<string, string>;
  /** The headers a presigned PUT must carry (method "put"). */
  headers?: Record<string, string>;
  /** What confirm takes. */
  token?: string;
  name?: string;
  expires_in?: number;
}

/** Experimental. `POST <resource>/files/<field>/confirm/`'s answer. */
export interface ConfirmAnswer {
  /** What the row's create or update takes as the field's value. */
  token: string;
  name: string;
  size: number;
  content_type: string;
}

/** Experimental. `GET <resource>/<id>/files/<field>/` with `Accept: application/json`. */
export interface FileLink {
  /** A signed URL that opens the file without a session, for `expires_in` seconds. */
  url: string;
  expires_in: number;
  name: string;
}

/** Experimental. What an upload gives the form. */
export interface ProtectedUploadResult {
  method: UploadMethod;
  /**
   * The field's value for the row's create or update: the chosen `File` itself
   * (method "api"), or a reference `File` carrying the confirmed token.
   */
  value: File;
  /** The confirmed token (null for method "api"), for a JSON payload of your own. */
  token: string | null;
  name: string;
  size: number;
  contentType: string;
}
