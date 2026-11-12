/** A line's picture in a square box, or a quiet placeholder when it has none. */
import { cn } from "@karni/ui";

export interface ItemImageProps {
  src: string | null | undefined;
  alt?: string;
  className?: string;
}

export function ItemImage({ src, alt = "", className }: ItemImageProps) {
  return (
    <div className={cn("aspect-square w-full overflow-hidden rounded-md bg-muted", className)}>
      {src ? (
        <img src={src} alt={alt} loading="lazy" className="h-full w-full object-cover" />
      ) : null}
    </div>
  );
}
