import type { Config } from "tailwindcss";
import defaultTheme from "tailwindcss/defaultTheme";

const brand = {
  50: "#eef2ff",
  100: "#e0e7ff",
  500: "#6366f1",
  600: "#4f46e5",
  900: "#312e81",
};

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand,
        primary: { DEFAULT: "#7c3aed", foreground: "#ffffff", hover: "#6d28d9" },
        danger: "rgb(220 38 38 / <alpha-value>)",
        background: "hsl(var(--app-bg) / <alpha-value>)",
        surface: "#fafafa",
      },
      fontFamily: {
        sans: ["Inter", ...defaultTheme.fontFamily.sans],
        display: ["Cal Sans", "sans-serif"],
      },
      borderRadius: { lg: "0.875rem", "4xl": "2rem" },
      boxShadow: { md: "0 4px 12px rgb(0 0 0 / 0.08)" },
      screens: { "3xl": "1920px" },
    },
  },
} satisfies Config;
