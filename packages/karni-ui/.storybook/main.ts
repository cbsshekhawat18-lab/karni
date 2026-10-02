import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  addons: ["@storybook/addon-essentials"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  // Serves public/mockServiceWorker.js for msw-storybook-addon
  // (generate it once with `npx msw init public/`).
  staticDirs: ["../public"],
};

export default config;
