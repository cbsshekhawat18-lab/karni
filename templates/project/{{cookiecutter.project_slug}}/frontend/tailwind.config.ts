import karniPreset from "@karni/ui/tailwind-preset";
import type { Config } from "tailwindcss";

// Tailwind v3 + the @karni/ui preset: maps bg-primary, text-muted-foreground,
// border, rounded-lg, ... onto the --karni-* tokens from @karni/ui/styles.css.
export default {
    presets: [karniPreset],
    content: [
        "./src/**/*.{ts,tsx}",
        // So Tailwind sees the classes used inside @karni/ui:
        "./node_modules/@karni/ui/dist/**/*.js",
    ],
} satisfies Config;
