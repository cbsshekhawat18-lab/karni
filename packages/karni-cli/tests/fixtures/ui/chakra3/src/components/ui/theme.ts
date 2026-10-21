import { createSystem, defaultConfig, defineConfig } from "@chakra-ui/react"

const config = defineConfig({
  theme: {
    tokens: {
      colors: {
        brand: {
          500: { value: "#0d9488" },
          600: { value: "#0f766e" },
        },
      },
      fonts: {
        body: { value: "Figtree, sans-serif" },
      },
      radii: {
        md: { value: "0.5rem" },
      },
    },
    semanticTokens: {
      colors: {
        primary: { value: { base: "{colors.brand.600}", _dark: "{colors.brand.500}" } },
        fg: { DEFAULT: { value: { base: "{colors.gray.900}", _dark: "{colors.gray.50}" } } },
      },
    },
    recipes: {},
  },
})

export const system = createSystem(defaultConfig, config)
