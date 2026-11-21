// Written by the karniGame() Vite preset from the assets folder. Do not edit.
import type { AssetEntry } from "@karni/game/assets";

declare global {
  interface KarniAssetGroups {
    readonly "cave": { readonly "bg": AssetEntry; };
    readonly "core": { readonly "coin": AssetEntry; readonly "hopper": AssetEntry; readonly "stages": AssetEntry; };
    readonly "meadow": { readonly "bg": AssetEntry; };
  }
}
export {};
