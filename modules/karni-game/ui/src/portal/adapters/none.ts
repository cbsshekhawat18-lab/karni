import type { PortalAdapter } from "../types";

/**
 * The adapter for a build without a portal SDK (a plain web page, itch.io,
 * local development): it starts at once and has no ads, so every ad call
 * on the portal reports "unavailable" and a rewarded ad gives nothing.
 */
export function noPortal(options: { name?: string } = {}): PortalAdapter {
  return {
    name: options.name ?? "none",
    init: () => Promise.resolve(),
  };
}

export default noPortal;
