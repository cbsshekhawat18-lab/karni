/**
 * How a line of a cart or an order reads, per kind.
 *
 * Commerce sells what every part registers (a product, a booking, a
 * course), and each kind reads differently on a line: a product shows its
 * size and colour, a booking its date and time, a course when it starts. A
 * part registers a renderer for its kind once at startup, and the cart, the
 * checkout, the buyer's order page and the staff's order page draw that
 * kind's lines through it:
 *
 *     registerLineRenderer("booking", ({ line }) => (
 *       <span>{line.name}<span className="block text-sm">{line.details[0]?.value}</span></span>
 *     ));
 *
 * Without one, a line shows its name (a link to the item's page where the
 * buyer may follow it) and its options in words (`LineDetails`), with the
 * SKU on the staff's page.
 *
 * Override / escape hatch: the same kind replaces a renderer,
 * `unregisterLineRenderer` takes one out, and `LineDescription` draws one
 * line the way the pages do, for a page of your own.
 */
import type { ComponentType } from "react";
import { CommerceLink } from "./routes";
import { LineDetails } from "./Totals";
import type { LineDetail } from "./types";

/** What a renderer gets of a line: the fields a cart line and an order line share. */
export interface LineView {
  id: string;
  kind: string;
  item: string;
  name: string;
  /** The item's page in the app, or "". */
  url: string;
  options: Record<string, unknown>;
  details: LineDetail[];
  quantity: number;
  /** The SKU (an order line's), when there is one. */
  sku?: string;
}

/** Where a line shows. */
export type LinePlace = "cart" | "checkout" | "order" | "staff";

/** What a line renderer receives. */
export interface LineRendererProps {
  line: LineView;
  place: LinePlace;
}

const RENDERERS = new Map<string, ComponentType<LineRendererProps>>();

/** Draw the lines of `kind` with `Component` (the same kind replaces it). */
export function registerLineRenderer(
  kind: string,
  Component: ComponentType<LineRendererProps>,
): void {
  RENDERERS.set(kind, Component);
}

/** Forget the renderer of `kind`. */
export function unregisterLineRenderer(kind: string): void {
  RENDERERS.delete(kind);
}

/** The renderer of `kind`, or undefined for the default. */
export function lineRenderer(kind: string): ComponentType<LineRendererProps> | undefined {
  return RENDERERS.get(kind);
}

/** The default line: its name (linked where the buyer may follow it), options, SKU. */
export function DefaultLine({ line, place }: LineRendererProps) {
  const linked = line.url !== "" && (place === "cart" || place === "order");
  return (
    <>
      {linked ? (
        <CommerceLink to={line.url} className="font-medium hover:underline">
          {line.name}
        </CommerceLink>
      ) : (
        <span className={place === "checkout" ? undefined : "font-medium"}>{line.name}</span>
      )}
      <LineDetails details={line.details} className={place === "staff" ? "text-xs" : undefined} />
      {place === "staff" && line.sku ? (
        <span className="block text-xs text-muted-foreground">{line.sku}</span>
      ) : null}
    </>
  );
}

/** One line as the commerce pages draw it: its kind's renderer, else the default. */
export function LineDescription({ line, place }: LineRendererProps) {
  const Own = RENDERERS.get(line.kind) ?? DefaultLine;
  return <Own line={line} place={place} />;
}
