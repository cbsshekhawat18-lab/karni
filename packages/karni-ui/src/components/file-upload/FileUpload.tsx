import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { SpinnerIcon } from "../primitives/icons";

registerComponentRole("file-upload", "FileUpload");

/** Why a file was refused by <FileUpload> (surfaced through `onReject`). */
export type FileUploadRejectReason = "accept" | "size";

/** What the `Dropzone` slot receives: the props of the button it replaces, plus its state. */
export interface FileUploadDropzoneProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "children"
> {
  /** Attach to the button: focus returns to it after a file is removed. */
  buttonRef: React.Ref<HTMLButtonElement>;
  /** A file is being dragged over the dropzone. */
  dragging: boolean;
  multiple: boolean;
  /** The `uploading` prop. */
  uploading: boolean;
  /** The `children` prop (custom content), or undefined for the default text. */
  children?: React.ReactNode;
}

/** What the `FileRow` slot receives: one current file. Render an <li>. */
export interface FileUploadFileRowProps {
  /** A pending `File`, or the URL string of a file already uploaded. */
  file: File | string;
  /** The file name (a URL's last path segment). */
  name: string;
  /** A pending file's size ("12 KB"); undefined for a URL. */
  size?: string;
  /** Removes the file; undefined when it cannot be removed (clearable=false, disabled, uploading). */
  onRemove?: () => void;
}

/** The parts of the picker a project can replace (`slots={{ FileRow: Thumbnail }}`). */
export interface FileUploadSlots {
  /** The drop target: a button that opens the file picker. */
  Dropzone: React.ComponentType<FileUploadDropzoneProps>;
  /** One row of the current-files list. */
  FileRow: React.ComponentType<FileUploadFileRowProps>;
}

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
  /**
   * The sentence shown (and announced) for a refused file. Default: "notes.txt
   * isn't an accepted file type." / "big.png is larger than 1.0 MB.". Return
   * null to show nothing (when `onReject` reports it elsewhere).
   */
  rejectionMessage?: (
    file: File,
    reason: FileUploadRejectReason,
    limits: { accept?: string; maxSize?: number },
  ) => React.ReactNode;
  /** An error to show under the dropzone (announced); marks the field invalid. */
  error?: React.ReactNode;
  /** True while the file uploads: the dropzone shows progress and takes no new files. */
  uploading?: boolean;
  id?: string;
  /** Forwarded to the hidden native file input. */
  name?: string;
  className?: string;
  /** Replaces the default dropzone content (escape hatch). */
  children?: React.ReactNode;
  /** Set false to hide the per-file remove affordance. Default true. */
  clearable?: boolean;
  /** Replaces the Dropzone or FileRow; see FileUploadSlots. */
  slots?: Partial<FileUploadSlots>;
  "aria-label"?: string;
  /** Ids of elements that label the dropzone (or point a <label htmlFor> at `id`). */
  "aria-labelledby"?: string;
  /** Ids of elements that describe the dropzone (help text, a form's error message). */
  "aria-describedby"?: string;
  /** Marks the dropzone invalid (a destructive border); `error` sets it too. */
  "aria-invalid"?: React.AriaAttributes["aria-invalid"];
  /** Called when focus leaves the dropzone (react-hook-form's onBlur). */
  onBlur?: React.FocusEventHandler<HTMLButtonElement>;
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

function defaultRejectionMessage(
  file: File,
  reason: FileUploadRejectReason,
  limits: { maxSize?: number },
): React.ReactNode {
  if (reason === "size" && limits.maxSize !== undefined) {
    return `${file.name} is larger than ${formatFileSize(limits.maxSize)}.`;
  }
  return `${file.name} isn't an accepted file type.`;
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

function DefaultDropzone({
  buttonRef,
  dragging,
  multiple,
  uploading,
  children,
  className,
  ...props
}: FileUploadDropzoneProps): React.ReactElement {
  let content = children;
  if (uploading) {
    content = (
      <>
        <SpinnerIcon className="h-5 w-5 animate-spin" />
        <span>Uploading…</span>
      </>
    );
  } else if (content === undefined) {
    content = (
      <>
        <UploadIcon className="h-5 w-5" />
        <span>
          {multiple
            ? "Drag and drop files here, or click to browse"
            : "Drag and drop a file here, or click to browse"}
        </span>
      </>
    );
  }
  return (
    <button
      ref={buttonRef}
      type="button"
      data-dragging={dragging ? "true" : undefined}
      className={cn(
        "flex w-full flex-col items-center justify-center gap-1 rounded-md border border-dashed border-input bg-background px-4 py-6 text-sm text-muted-foreground ring-offset-background transition-colors hover:border-ring hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive data-[dragging=true]:border-ring data-[dragging=true]:bg-accent data-[dragging=true]:text-accent-foreground",
        // Busy, not unavailable: the progress message stays fully legible.
        uploading && "disabled:cursor-progress disabled:opacity-100",
        className,
      )}
      {...props}
    >
      {content}
    </button>
  );
}

function DefaultFileRow({
  file,
  name,
  size,
  onRemove,
}: FileUploadFileRowProps): React.ReactElement {
  return (
    <li className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted-subtle px-3 py-1.5 text-sm">
      {typeof file === "string" ? (
        <a
          href={file}
          target="_blank"
          rel="noreferrer"
          className="truncate font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {name}
        </a>
      ) : (
        <span className="truncate">
          {name}
          <span className="ml-2 text-xs text-muted-foreground">{size}</span>
        </span>
      )}
      {onRemove !== undefined ? (
        <button
          type="button"
          aria-label={`Remove ${name}`}
          onClick={onRemove}
          className="rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <XIcon className="h-4 w-4" />
        </button>
      ) : null}
    </li>
  );
}

/** The default pieces of the picker, for wrapping one. */
export const defaultFileUploadSlots: FileUploadSlots = {
  Dropzone: DefaultDropzone,
  FileRow: DefaultFileRow,
};

/**
 * Drag-and-drop or click-to-browse file picker that shows the current file and the pending ones.
 *
 * Contract "FileUpload".
 *
 * Shows an existing uploaded value (URL string) as a link, pending `File`
 * values with name and size, and emits `File` objects — the hooks layer turns
 * them into multipart bodies per amendment D2.
 *
 * Keyboard and screen readers: the dropzone is a button (Enter or Space opens
 * the picker), labelled by its text, `aria-label`, `aria-labelledby` or a
 * <label htmlFor={id}>. A refused file and the `error` prop are announced and
 * linked through aria-describedby; `aria-invalid` (or `error`) marks it
 * invalid. Removing a file returns focus to the dropzone.
 *
 * Escape hatches: `slots` replaces the Dropzone or FileRow, `children`
 * replaces the dropzone's content, `rejectionMessage` rewords refusals.
 */
export const FileUpload = React.forwardRef<HTMLButtonElement, FileUploadProps>(
  function FileUpload(props, ref): React.ReactElement {
    const {
      value = null,
      onChange,
      accept,
      multiple = false,
      disabled = false,
      maxSize,
      onReject,
      rejectionMessage = defaultRejectionMessage,
      error,
      uploading = false,
      id,
      name,
      className,
      children,
      clearable = true,
      slots,
    } = props;
    const { Dropzone, FileRow } = { ...defaultFileUploadSlots, ...slots };

    const inputRef = React.useRef<HTMLInputElement>(null);
    const dropzoneRef = React.useRef<HTMLButtonElement>(null);
    // The forwarded ref is the dropzone button: what a label, aria-describedby and form focus point at.
    React.useImperativeHandle(ref, () => dropzoneRef.current as HTMLButtonElement, []);
    const messageId = React.useId();
    const [dragging, setDragging] = React.useState(false);
    const [rejections, setRejections] = React.useState<readonly React.ReactNode[]>([]);

    const blocked = disabled || uploading;
    const entries: ReadonlyArray<File | string> =
      value == null ? [] : Array.isArray(value) ? value : [value as File | string];

    const acceptFiles = (list: ArrayLike<File>): void => {
      if (blocked) return;
      const accepted: File[] = [];
      const refused: React.ReactNode[] = [];
      for (const file of Array.from(list)) {
        let reason: FileUploadRejectReason | null = null;
        if (!matchesAccept(file, accept)) reason = "accept";
        else if (maxSize !== undefined && file.size > maxSize) reason = "size";
        if (reason === null) {
          accepted.push(file);
          continue;
        }
        onReject?.(file, reason);
        const message = rejectionMessage(file, reason, { accept, maxSize });
        if (message != null && message !== false) refused.push(message);
      }
      setRejections(refused);
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
      if (blocked) return;
      acceptFiles(event.dataTransfer.files);
    };

    const handleDragOver = (event: React.DragEvent<HTMLButtonElement>): void => {
      event.preventDefault();
      if (!blocked) setDragging(true);
    };

    const removeEntry = (index: number): void => {
      if (onChange === undefined) return;
      // The row (and its button) is about to go: keep the keyboard on the field.
      dropzoneRef.current?.focus();
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

    const messages: React.ReactNode[] = error != null && error !== false ? [error] : [];
    messages.push(...rejections);
    const describedBy =
      [props["aria-describedby"], messages.length > 0 ? messageId : undefined]
        .filter(Boolean)
        .join(" ") || undefined;
    const invalid = props["aria-invalid"] ?? (error != null && error !== false ? true : undefined);

    return (
      <div className={cn("space-y-2", className)}>
        <Dropzone
          buttonRef={dropzoneRef}
          id={id}
          disabled={blocked}
          aria-label={props["aria-label"]}
          aria-labelledby={props["aria-labelledby"]}
          aria-describedby={describedBy}
          aria-invalid={invalid}
          aria-busy={uploading || undefined}
          onBlur={props.onBlur}
          onClick={() => inputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          dragging={dragging}
          multiple={multiple}
          uploading={uploading}
        >
          {children}
        </Dropzone>
        <input
          ref={inputRef}
          type="file"
          name={name}
          accept={accept}
          multiple={multiple}
          disabled={blocked}
          onChange={handleInputChange}
          tabIndex={-1}
          aria-hidden="true"
          className="sr-only"
        />
        <span className="sr-only" role="status">
          {uploading ? "Uploading…" : ""}
        </span>
        {messages.length > 0 ? (
          <div id={messageId} className="space-y-1">
            {messages.map((message, index) => (
              <p key={index} role="alert" className="text-sm text-destructive">
                {message}
              </p>
            ))}
          </div>
        ) : null}
        {entries.length > 0 ? (
          <ul className="space-y-1">
            {entries.map((entry, index) => {
              const label = typeof entry === "string" ? fileBasename(entry) : entry.name;
              return (
                <FileRow
                  key={typeof entry === "string" ? `url-${entry}` : `file-${entry.name}-${index}`}
                  file={entry}
                  name={label}
                  size={typeof entry === "string" ? undefined : formatFileSize(entry.size)}
                  onRemove={clearable && !blocked ? () => removeEntry(index) : undefined}
                />
              );
            })}
          </ul>
        ) : null}
      </div>
    );
  },
);
