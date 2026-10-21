import { extendTheme, type ThemeConfig } from "@chakra-ui/react";

const config: ThemeConfig = { initialColorMode: "light", useSystemColorMode: false };

const theme = extendTheme({
  config,
  colors: {
    brand: {
      50: "#e3f2ff",
      100: "#b3daff",
      200: "#81c1ff",
      500: "#1a73e8",
      600: "#155fc0",
      900: "#0a2a5c",
    },
  },
  semanticTokens: {
    colors: {
      primary: { default: "brand.500", _dark: "brand.200" },
      border: { default: "gray.200", _dark: "whiteAlpha.300" },
      danger: "#e53e3e",
      "chakra-body-bg": { _light: "#ffffff", _dark: "#1a202c" },
    },
  },
  fonts: {
    heading: `"Poppins", sans-serif`,
    body: `"Inter", sans-serif`,
    mono: "Menlo, monospace",
  },
  radii: { md: "0.5rem", lg: "0.75rem", base: "0.25rem" },
  shadows: { md: "0 4px 6px rgba(0,0,0,0.1)", outline: "0 0 0 3px #81c1ff" },
  components: { Button: { baseStyle: { fontWeight: "semibold" } } },
});

export default theme;
