import type { Assets } from "@karni/game/assets";
import { manifest } from "virtual:karni-game/assets";

export const assetManifest = manifest;
export type GameAssets = Assets<typeof manifest>;

export interface StageInfo {
  title: string;
  platform: string;
  theme: string;
}

/** The stages in the order they come. Each is a group of the assets folder, with its backdrop. */
export const STAGES = ["meadow", "cave"] as const;
export type StageName = (typeof STAGES)[number];

/** Stage data from `assets/core/stages.json`, checked before use: a data file arrives as `unknown`. */
export function stageInfo(assets: GameAssets, stage: StageName): StageInfo {
  const table = assets.data("core", "stages") as Record<string, Partial<StageInfo>>;
  const info = table[stage];
  if (!info || typeof info.title !== "string" || typeof info.platform !== "string") {
    throw new Error(`assets/core/stages.json has no usable entry for "${stage}"`);
  }
  return { title: info.title, platform: info.platform, theme: info.theme ?? stage };
}
