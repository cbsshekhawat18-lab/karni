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
  /**
   * The game API this build calls from another origin (`KARNI_GAME_API_URL`,
   * `https://api.example.com`), or null: the page's own origin.
   */
  export const gameApiUrl: string | null;
  /** The adapter of the build's portal, and no other portal's. */
  export function createPortalAdapter(): PortalAdapter;
  export default createPortalAdapter;
}

/**
 * Merged by the file the preset writes when `assets.types` is set, so
 * `assets.image("stage1", "hero")` checks the group and the file name.
 */
// Empty on purpose: the generated file adds the groups to it.
// eslint-disable-next-line @typescript-eslint/no-empty-object-type
interface KarniAssetGroups {}

declare module "virtual:karni-game/assets" {
  import type { AssetEntry, AssetManifest } from "@karni/game/assets";
  /** The files of the assets folder, by group: its first-level folders, and `core` for the files directly in it. */
  export const manifest: [keyof KarniAssetGroups] extends [never]
    ? AssetManifest
    : { readonly groups: { readonly [G in keyof KarniAssetGroups]: KarniAssetGroups[G] } };
  /** The hosts this build may fetch files from (the portal's, the game API's and the project's own). */
  export const assetHosts: readonly string[];
  /** The download budget of each group, in bytes. */
  export const assetBudgets: Readonly<Record<string, number>>;
  export type { AssetEntry };
}
