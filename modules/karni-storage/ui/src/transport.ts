/**
 * Sending a file straight to the bucket, with upload progress.
 *
 * `fetch` cannot report upload progress, so the default transport is
 * XMLHttpRequest. A presigned POST is a multipart form (the policy's fields
 * first, the file last); a presigned PUT is the file as the body with the
 * signed headers. Escape hatch: pass a `transport` of your own to
 * `useProtectedUpload` (a service worker, a resumable uploader, a test fake).
 */

/** Experimental. One request to the bucket. */
export interface BucketRequest {
  method: "POST" | "PUT";
  url: string;
  body: FormData | File;
  headers: Record<string, string>;
  onProgress: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}

/** Experimental. Sends one request to the bucket; resolves when the bucket accepted it. */
export type BucketTransport = (request: BucketRequest) => Promise<void>;

/** Experimental. The bucket refused the file (or could not be reached: status 0). */
export class BucketUploadError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, body: string) {
    super(
      status === 0
        ? "The file could not be sent to storage (network error or blocked by CORS)."
        : `Storage refused the file (HTTP ${status}).`,
    );
    this.name = "BucketUploadError";
    this.status = status;
    this.body = body;
  }
}

/** Experimental. The default transport: XMLHttpRequest, for its upload progress events. */
export const xhrTransport: BucketTransport = (request) =>
  new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(request.method, request.url);
    for (const [name, value] of Object.entries(request.headers)) {
      xhr.setRequestHeader(name, value);
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) request.onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new BucketUploadError(xhr.status, String(xhr.responseText ?? "")));
    };
    xhr.onerror = () => reject(new BucketUploadError(0, ""));
    const abort = (): void => {
      xhr.abort();
      reject(new DOMException("The upload was cancelled.", "AbortError"));
    };
    if (request.signal !== undefined) {
      if (request.signal.aborted) {
        abort();
        return;
      }
      request.signal.addEventListener("abort", abort, { once: true });
    }
    xhr.send(request.body);
  });
