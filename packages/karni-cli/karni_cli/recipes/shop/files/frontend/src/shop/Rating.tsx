// An average rating as five stars, with the number of reviews. Screen readers hear it
// in words ("Rated 4.5 out of 5 from 12 reviews").
import { cn } from "@karni/ui";

export function Stars({
  value,
  className,
}: {
  value: number;
  className?: string;
}) {
  return (
    <span aria-hidden="true" className={cn("inline-flex", className)}>
      {[1, 2, 3, 4, 5].map((star) => (
        <span
          key={star}
          className={
            value >= star - 0.25 ? "text-primary" : "text-muted-foreground/40"
          }
        >
          ★
        </span>
      ))}
    </span>
  );
}

export function Rating({
  average,
  count,
  className,
}: {
  average: string | null;
  count: number;
  className?: string;
}) {
  if (average === null || count === 0) return null;
  const value = Number(average);
  const reviews = count === 1 ? "1 review" : `${String(count)} reviews`;
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm", className)}>
      <Stars value={value} />
      <span className="sr-only">
        Rated {value.toFixed(1)} out of 5 from {reviews}
      </span>
      <span aria-hidden="true" className="text-muted-foreground">
        {value.toFixed(1)} ({count})
      </span>
    </span>
  );
}
