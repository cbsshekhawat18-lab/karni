import { createTheme, type MantineColorsTuple } from "@mantine/core";

const brand: MantineColorsTuple = [
  "#f0ebff",
  "#ddd2fa",
  "#b8a2f3",
  "#916eec",
  "#7042e6",
  "#5b27e3",
  "#5019e2",
  "#410ec9",
  "#3909b5",
  "#2f05a0",
];

export const theme = createTheme({
  primaryColor: "brand",
  colors: {
    brand,
    accent: [
      "#e6fcf5",
      "#c3fae8",
      "#96f2d7",
      "#63e6be",
      "#38d9a9",
      "#20c997",
      "#12b886",
      "#0ca678",
      "#099268",
      "#087f5b",
    ],
  },
  fontFamily: "Outfit, sans-serif",
  fontFamilyMonospace: "JetBrains Mono, monospace",
  headings: { fontFamily: "Outfit, sans-serif" },
  defaultRadius: "md",
  radius: { md: "0.625rem" },
  shadows: { md: "0 2px 8px rgb(0 0 0 / 0.12)", xl: "0 12px 32px rgb(0 0 0 / 0.2)" },
  spacing: { md: "1.25rem" },
  other: { sidebarWidth: 280 },
});
