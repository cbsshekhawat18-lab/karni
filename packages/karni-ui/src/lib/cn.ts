import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merges class names: clsx semantics for conditionals plus tailwind-merge
 * conflict resolution, so consumer-supplied `className` always wins over a
 * component's own Tailwind classes. Every @karni/ui component funnels its
 * `className` prop through this.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
