import type { Preview } from "@storybook/react";
import { initialize, mswLoader } from "msw-storybook-addon";
import * as React from "react";
import "./tailwind.css";

/**
 * MSW is initialized once for every story; stories opt in to handlers via
 * `parameters.msw.handlers` (msw-storybook-addon@^2). Unhandled requests
 * pass through so plain component stories need no handlers at all.
 */
initialize({ onUnhandledRequest: "bypass" });

/** Applies the theme toolbar choice by toggling `.dark` on <html>. */
function ThemeDecorator(props: { theme: string; children: React.ReactNode }): React.ReactElement {
  const dark = props.theme === "dark";
  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  return (
    <div className="min-h-screen bg-background p-8 text-foreground antialiased">
      {props.children}
    </div>
  );
}

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    // The theme toolbar owns the canvas background (via bg-background).
    backgrounds: { disable: true },
  },
  globalTypes: {
    theme: {
      description: "Color scheme — toggles the `.dark` class on <html>",
      toolbar: {
        title: "Theme",
        icon: "mirror",
        items: [
          { value: "light", title: "Light", icon: "sun" },
          { value: "dark", title: "Dark", icon: "moon" },
        ],
        dynamicTitle: true,
      },
    },
  },
  initialGlobals: {
    theme: "light",
  },
  loaders: [mswLoader],
  decorators: [
    (Story, context) => (
      <ThemeDecorator theme={String(context.globals.theme ?? "light")}>
        <Story />
      </ThemeDecorator>
    ),
  ],
};

export default preview;
