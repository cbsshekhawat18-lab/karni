/**
 * Local Tailwind config for Storybook and development only.
 * Consumers use the published preset (see ./tailwind-preset.ts and README).
 */
import type { Config } from "tailwindcss";
import karniPreset from "./tailwind-preset";

const config: Config = {
  presets: [karniPreset],
  content: ["./src/**/*.{ts,tsx}", "./.storybook/**/*.{ts,tsx}"],
};

export default config;
