/**
 * ProtectedFileLink and ProtectedImage: a protected file's download link and
 * image, for any auth mode.
 *
 * The API gives a protected field as its download path. With session auth a
 * plain link opens it, but a token sent in a header cannot ride on an `<a>` or
 * an `<img>`. These components ask the path for a short-lived signed link
 * (`useProtectedFileLink`) and open or show that instead.
 *
 * Experimental: may change in a minor release, with a CHANGELOG entry.
 */
import { cn, useKarniClient } from "@karni/ui";
import * as React from "react";
import { useProtectedFileLink } from "./hooks";
import type { FileLink } from "./types";

export interface ProtectedFileLinkProps extends Omit<
  React.AnchorHTMLAttributes<HTMLAnchorElement>,
  "href"
> {
  /** The field's value as the API gives it: the download path. */
  href: string | null | undefined;
  /** Save the file instead of opening it. */
  download?: boolean;
  /** Opens the signed URL. Default: a new tab, or the same one for a download. */
  open?: (url: string) => void;
  children?: React.ReactNode;
}

function lastSegment(path: string): string {
  const clean = path.split(/[?#]/, 1)[0] ?? path;
  const parts = clean.split("/").filter((part) => part !== "");
  return parts[parts.length - 1] ?? path;
}

/**
 * Experimental. A link to a protected file: on click it asks the download path
 * for a signed link and opens it. Nothing is fetched before the click.
 */
export function ProtectedFileLink({
  href,
  download = false,
  open,
  children,
  className,
  onClick,
  ...rest
}: ProtectedFileLinkProps): React.ReactElement | null {
  const client = useKarniClient();
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState<string | null>(null);
  if (href === null || href === undefined || href === "") return null;

  const follow = async (event: React.MouseEvent<HTMLAnchorElement>): Promise<void> => {
    onClick?.(event);
    if (event.defaultPrevented) return;
    event.preventDefault();
    setBusy(true);
    setFailed(null);
    try {
      const link = await client.request<FileLink>(href, {
        query: { download: download ? "1" : undefined },
      });
      if (open !== undefined) open(link.url);
      else if (download) window.location.assign(link.url);
      else window.open(link.url, "_blank", "noopener");
    } catch (caught) {
      setFailed(caught instanceof Error ? caught.message : "The file could not be opened.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="inline-flex flex-col">
      <a
        {...rest}
        href={href}
        aria-busy={busy || undefined}
        className={cn(
          "font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
        onClick={(event) => void follow(event)}
      >
        {children ?? lastSegment(href)}
      </a>
      {failed !== null ? (
        <span role="alert" className="text-sm text-destructive">
          {failed}
        </span>
      ) : null}
    </span>
  );
}

export interface ProtectedImageProps extends Omit<
  React.ImgHTMLAttributes<HTMLImageElement>,
  "src"
> {
  /** The field's value as the API gives it: the download path. */
  src: string | null | undefined;
  /** A thumbnail size name (KARNI_STORAGE_THUMBNAIL_SIZES), e.g. "small". */
  size?: string;
  /** What shows while the link loads, or when there is none. */
  fallback?: React.ReactNode;
}

/** Experimental. A protected image (or one of its thumbnails) through a signed link. */
export function ProtectedImage({
  src,
  size,
  fallback = null,
  alt,
  ...rest
}: ProtectedImageProps): React.ReactElement | null {
  const link = useProtectedFileLink(src, { size });
  if (link.data === undefined) return <>{fallback}</>;
  return <img {...rest} alt={alt ?? link.data.name} src={link.data.url} />;
}
