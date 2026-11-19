/**
 * Types for a game built with the `karniGame()` Vite preset. Add them once:
 *
 *   /// <reference types="@karni/game/client" />
 */

/** True in `vite dev`, false in every build: guard debug hooks with it so builds drop them. */
declare const __KARNI_GAME_DEV__: boolean;
/** The portal this build is for ("web", "poki", ...). */
declare const __KARNI_GAME_PORTAL__: string;

declare module "virtual:karni-game/portal" {
  import type { PortalAdapter } from "@karni/game";
  /** The name of the build's portal. */
  export const portalName: string;
  /** The adapter options the build resolved from the project's config. */
  export const portalOptions: Readonly<Record<string, string | number | boolean>>;
  /** The adapter of the build's portal, and no other portal's. */
  export function createPortalAdapter(): PortalAdapter;
  export default createPortalAdapter;
}
