import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("file-upload", "FileUpload");

/** Why a file was refused by <FileUpload> (surfaced through `onReject`). */
export type FileUploadRejectReason = "accept" | "size";

export interface FileUploadProps {
  /**
   * Current value. A `string` is an existing uploaded file (the display URL a
   * karni backend returns); a `File` is a pending upload. Arrays are for
   * `multiple` mode and may mix both.
   */
  value?: File | string | ReadonlyArray<File | string> | null;
  /**
   * Emits the newly chosen `File` (or `File[]` when `multiple`), and `null`
   * when the value is cleared. Existing URL strings are display-only: they
   * can be removed (emitting `null` / the remaining files) but never re-emitted.
   */
  onChange?: (value: File | File[] | null) => void;
  /** Same grammar as the native `accept` attribute (".png,image/*,application/pdf"). */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  /** Maximum size per file, in bytes. Larger files are rejected via `onReject`. */
  maxSize?: number;
  /** Called once per refused file with the reason ("accept" | "size"). */
  onReject?: (file: File, reason: FileUploadRejectReason) => void;
  id?: string;
  /** Forwarded to the hidden native file input. */
  name?: string;
  className?: string;
  /** Replaces the default dropzone content (escape hatch). */
  children?: React.ReactNode;
  /** Set false to hide the per-file remove affordance. Default true. */
  clearable?: boolean;
  "aria-label"?: string;
}

function matchesAccept(file: File, accept: string | undefined): boolean {
  if (accept === undefined || accept.trim() === "") return true;
  const tokens = accept
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter((token) => token !== "");
  if (tokens.length === 0) return true;
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return tokens.some((token) => {
    if (token.startsWith(".")) return name.endsWith(token);
    if (token.endsWith("/*")) return type.startsWith(token.slice(0, -1));
    return type === token;
  });
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileBasename(url: string): string {
  const withoutQuery = url.split(/[?#]/, 1)[0] ?? url;
  const segments = withoutQuery.split("/").filter((segment) => segment !== "");
  return segments[segments.length - 1] ?? url;
}

function UploadIcon(props: React.SVGAttributes<SVGSVGElement>): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <path d="M21 15v3a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3v-3" />
      <polyline points="7 8 12 3 17 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function XIcon(props: React.SVGAttributes<SVGSVGElement>): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

/**
 * Drag-and-drop / click-to-browse file picker (contract "FileUpload").
 *
 * Shows an existing uploaded value (URL string) as a link, pending `File`
 * values with name and size, and emits `File` objects — the hooks layer turns
 * them into multipart bodies per amendment D2.
 */
export function FileUpload(props: FileUploadProps): React.ReactElement {
  const {
    value = null,
    onChange,
    accept,
    multiple = false,
    disabled = false,
    maxSize,
    onReject,
    id,
    name,
    className,
    children,
    clearable = true,
  } = props;

  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);

  const entries: ReadonlyArray<File | string> =
    value == null ? [] : Array.isArray(value) ? value : [value as File | string];

  const acceptFiles = (list: ArrayLike<File>): void => {
    if (disabled) return;
    const accepted: File[] = [];
    for (const file of Array.from(list)) {
      if (!matchesAccept(file, accept)) {
        onReject?.(file, "accept");
        continue;
      }
      if (maxSize !== undefined && file.size > maxSize) {
        onReject?.(file, "size");
        continue;
      }
      accepted.push(file);
    }
    if (accepted.length === 0) return;
    onChange?.(multiple ? accepted : accepted[0]);
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
    if (event.target.files !== null) acceptFiles(event.target.files);
    // Reset so selecting the same file again re-fires the change event.
    event.target.value = "";
  };

  const handleDrop = (event: React.DragEvent<HTMLButtonElement>): void => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    acceptFiles(event.dataTransfer.files);
  };

  const handleDragOver = (event: React.DragEvent<HTMLButtonElement>): void => {
    event.preventDefault();
    if (!disabled) setDragging(true);
  };

  const removeEntry = (index: number): void => {
    if (onChange === undefined) return;
    const remaining = entries.filter((_, i) => i !== index);
    if (remaining.length === 0) {
      onChange(null);
      return;
    }
    // Existing URL strings cannot be re-emitted (onChange carries File values
    // only); the remaining pending files are kept.
    const files = remaining.filter((entry): entry is File => typeof entry !== "string");
    if (multiple) {
      onChange(files);
    } else {
      onChange(files[0] ?? null);
    }
  };

  return (
    <div className={cn("space-y-2", className)}>
      <button
        type="button"
        id={id}
        disabled={disabled}
        aria-label={props["aria-label"]}
        onClick={() => inputRef.current?.click()}
        onDragOver={handleDragOver}
        onDragEnter={handleDragOver}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        data-dragging={dragging ? "true" : undefined}
        className="flex w-full flex-col items-center justify-center gap-1 rounded-md border border-dashed border-input bg-background px-4 py-6 text-sm text-muted-foreground transition-colors hover:border-ring hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[dragging=true]:border-ring data-[dragging=true]:bg-accent data-[dragging=true]:text-accent-foreground"
      >
        {children ?? (
          <>
            <UploadIcon className="h-5 w-5" />
            <span>
              {multiple
                ? "Drag and drop files here, or click to browse"
                : "Drag and drop a file here, or click to browse"}
            </span>
          </>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        name={name}
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={handleInputChange}
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
      />
      {entries.length > 0 ? (
        <ul className="space-y-1">
          {entries.map((entry, index) => {
            const label = typeof entry === "string" ? fileBasename(entry) : entry.name;
            return (
              <li
                key={typeof entry === "string" ? `url-${entry}` : `file-${entry.name}-${index}`}
                className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/50 px-3 py-1.5 text-sm"
              >
                {typeof entry === "string" ? (
                  <a
                    href={entry}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate font-medium text-primary underline underline-offset-4"
                  >
                    {label}
                  </a>
                ) : (
                  <span className="truncate">
                    {entry.name}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {formatFileSize(entry.size)}
                    </span>
                  </span>
                )}
                {clearable && !disabled ? (
                  <button
                    type="button"
                    aria-label={`Remove ${label}`}
                    onClick={() => removeEntry(index)}
                    className="rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <XIcon className="h-4 w-4" />
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
