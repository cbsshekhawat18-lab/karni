/**
 * The hooks of @karni/storage-ui: a direct upload with progress and its
 * confirm step, and the signed link of a protected file.
 *
 * Experimental: these may change in a minor release, with a CHANGELOG entry.
 */
import { useKarniClient } from "@karni/ui";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { xhrTransport } from "./transport";
import type { BucketTransport } from "./transport";
import { UPLOAD_REFERENCE_TYPE } from "./types";
import type { ConfirmAnswer, FileLink, ProtectedUploadResult, UploadAnswer } from "./types";

/** Experimental. Where one upload is. */
export type ProtectedUploadStatus =
  "idle" | "preparing" | "uploading" | "confirming" | "done" | "error";

export interface UseProtectedUploadOptions {
  /** The resource's API path, as its viewset is routed: "products". */
  resource: string;
  /** The protected field's name: "manual". */
  field: string;
  /** Sends the file to the bucket. Default: XMLHttpRequest, with progress. */
  transport?: BucketTransport;
}

export interface UseProtectedUploadResult {
  /** Uploads one file and resolves with the field's value for the row's save. */
  upload: (file: File, options?: { signal?: AbortSignal }) => Promise<ProtectedUploadResult>;
  /** Back to idle (after an error, or to start again). */
  reset: () => void;
  status: ProtectedUploadStatus;
  /** 0 to 1 while the file travels to the bucket. */
  progress: number;
  error: Error | null;
  /** True from the upload step until confirm answers. */
  uploading: boolean;
}

/** Experimental. The value a row's save takes for a confirmed upload: a file part carrying the token. */
export function uploadReference(token: string, name: string): File {
  return new File([token], name, { type: UPLOAD_REFERENCE_TYPE });
}

function resourcePath(resource: string, field: string, step: "upload" | "confirm"): string {
  const trimmed = resource.replace(/^\/+|\/+$/g, "");
  return `/${trimmed}/files/${field}/${step}/`;
}

/**
 * Experimental. A direct upload of one file to a protected field, with progress.
 *
 * 1. `POST <resource>/files/<field>/upload/` with the file's name, type and size.
 *    On local storage the answer is method "api": the value is the file itself,
 *    sent with the row.
 * 2. The file goes straight to the bucket: a presigned POST (policy fields,
 *    then the file) or a presigned PUT (the file, with the signed headers).
 * 3. `POST <resource>/files/<field>/confirm/`: the server checks the object's
 *    size and type and answers a token. The value is a reference `File`
 *    carrying it ({@link uploadReference}), which the row's create or update takes.
 *
 * Escape hatch: `transport` replaces the request to the bucket.
 */
export function useProtectedUpload({
  resource,
  field,
  transport = xhrTransport,
}: UseProtectedUploadOptions): UseProtectedUploadResult {
  const client = useKarniClient();
  const [status, setStatus] = React.useState<ProtectedUploadStatus>("idle");
  const [progress, setProgress] = React.useState(0);
  const [error, setError] = React.useState<Error | null>(null);

  const reset = React.useCallback(() => {
    setStatus("idle");
    setProgress(0);
    setError(null);
  }, []);

  const upload = React.useCallback(
    async (file: File, options?: { signal?: AbortSignal }): Promise<ProtectedUploadResult> => {
      setError(null);
      setProgress(0);
      setStatus("preparing");
      try {
        const answer = await client.request<UploadAnswer>(resourcePath(resource, field, "upload"), {
          method: "POST",
          body: { name: file.name, content_type: file.type, size: file.size },
          signal: options?.signal,
        });
        if (answer.method === "api") {
          setProgress(1);
          setStatus("done");
          return {
            method: "api",
            value: file,
            token: null,
            name: file.name,
            size: file.size,
            contentType: file.type,
          };
        }
        if (answer.url === undefined || answer.token === undefined) {
          throw new Error("The upload step gave no URL to send the file to.");
        }
        setStatus("uploading");
        const onProgress = (loaded: number, total: number): void => {
          setProgress(total > 0 ? Math.min(1, loaded / total) : 0);
        };
        if (answer.method === "post") {
          const form = new FormData();
          for (const [key, value] of Object.entries(answer.fields ?? {})) form.append(key, value);
          form.append("file", file);
          await transport({
            method: "POST",
            url: answer.url,
            body: form,
            headers: {},
            onProgress,
            signal: options?.signal,
          });
        } else {
          await transport({
            method: "PUT",
            url: answer.url,
            body: file,
            headers: answer.headers ?? {},
            onProgress,
            signal: options?.signal,
          });
        }
        setProgress(1);
        setStatus("confirming");
        const confirmed = await client.request<ConfirmAnswer>(
          resourcePath(resource, field, "confirm"),
          { method: "POST", body: { token: answer.token }, signal: options?.signal },
        );
        setStatus("done");
        return {
          method: answer.method,
          value: uploadReference(confirmed.token, file.name),
          token: confirmed.token,
          name: confirmed.name,
          size: confirmed.size,
          contentType: confirmed.content_type,
        };
      } catch (caught) {
        const failure = caught instanceof Error ? caught : new Error(String(caught));
        setError(failure);
        setStatus("error");
        throw failure;
      }
    },
    [client, resource, field, transport],
  );

  const uploading = status === "preparing" || status === "uploading" || status === "confirming";
  return { upload, reset, status, progress, error, uploading };
}

export interface UseProtectedFileLinkOptions {
  /** A thumbnail size name (KARNI_STORAGE_THUMBNAIL_SIZES), e.g. "small". */
  size?: string;
  /** Ask for an attachment rather than inline display. */
  download?: boolean;
  /** Fetch the link at once (default true). False waits for `refetch()`. */
  enabled?: boolean;
}

/**
 * Experimental. The signed link of a protected file: `GET` its download path
 * with `Accept: application/json` (the client sends the session or token), so
 * the result opens in an `<img>`, a new tab or a download without credentials.
 *
 * `href` is the field's value as the API gives it (the download path). The
 * link is cached for a little less than it lives.
 */
export function useProtectedFileLink(
  href: string | null | undefined,
  { size, download, enabled = true }: UseProtectedFileLinkOptions = {},
): ReturnType<typeof useQuery<FileLink>> {
  const client = useKarniClient();
  return useQuery<FileLink>({
    queryKey: ["karni-storage", "link", href ?? "", size ?? "", download === true],
    enabled: enabled && typeof href === "string" && href !== "",
    queryFn: ({ signal }) =>
      client.request<FileLink>(String(href), {
        query: { size, download: download === true ? "1" : undefined },
        signal,
      }),
    staleTime: (query) => {
      const lives = query.state.data?.expires_in ?? 60;
      return Math.max(0, lives - 30) * 1000;
    },
  });
}
