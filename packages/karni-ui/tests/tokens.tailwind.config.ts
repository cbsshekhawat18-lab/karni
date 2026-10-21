/**
 * The preset with no content globs, for tests/tokens.test.ts: the entry's
 * @source lines choose the files (shipped components, not tests or stories).
 */
import type { Config } from "tailwindcss";
import karniPreset from "../tailwind-preset";

const config: Config = { presets: [karniPreset], content: [] };

export default config;
