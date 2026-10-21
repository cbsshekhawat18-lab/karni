/**
 * axe-core over every Storybook story of the app shell, the support
 * components and the primitives: each story renders (its args, render
 * function and decorators, through composeStories) and axe checks the whole
 * document, portals included, against the WCAG 2.x A and AA rules.
 *
 * Colour contrast is off here, because jsdom does not compute styles;
 * tests/contrast.test.ts checks every token pair the components use instead.
 */
import { composeStories } from "@storybook/react";
import { act, cleanup, render } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as karniMark from "../src/components/brand/karni-mark.stories";
import * as chart from "../src/components/chart/data-chart.stories";
import * as emptyState from "../src/components/empty-state/empty-state.stories";
import * as fileUpload from "../src/components/file-upload/file-upload.stories";
import * as layout from "../src/components/layout/layout.stories";
import * as modal from "../src/components/modal/modal.stories";
import * as page from "../src/components/page/page.stories";
import * as button from "../src/components/primitives/button.stories";
import * as checkbox from "../src/components/primitives/checkbox.stories";
import * as dropdownMenu from "../src/components/primitives/dropdown-menu.stories";
import * as input from "../src/components/primitives/input.stories";
import * as label from "../src/components/primitives/label.stories";
import * as select from "../src/components/primitives/select.stories";
import * as skeleton from "../src/components/primitives/skeleton.stories";
import * as switchStories from "../src/components/primitives/switch.stories";
import * as tabs from "../src/components/primitives/tabs.stories";
import * as textarea from "../src/components/primitives/textarea.stories";
import * as stat from "../src/components/stat/stat.stories";
import { resetToastStore } from "../src/components/toast/toast-store";
import * as toast from "../src/components/toast/toaster.stories";
import * as theme from "../src/theme/theme.stories";

const MODULES = {
  DataChart: composeStories(chart),
  EmptyState: composeStories(emptyState),
  FileUpload: composeStories(fileUpload),
  KarniMark: composeStories(karniMark),
  Layout: composeStories(layout),
  Modal: composeStories(modal),
  Page: composeStories(page),
  Toast: composeStories(toast),
  Stat: composeStories(stat),
  ThemeToggle: composeStories(theme),
  Button: composeStories(button),
  Checkbox: composeStories(checkbox),
  DropdownMenu: composeStories(dropdownMenu),
  Input: composeStories(input),
  Label: composeStories(label),
  Select: composeStories(select),
  Skeleton: composeStories(skeleton),
  Switch: composeStories(switchStories),
  Tabs: composeStories(tabs),
  Textarea: composeStories(textarea),
};

const OPTIONS: axe.RunOptions = {
  runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
  rules: { "color-contrast": { enabled: false } },
};

function describeViolations(violations: readonly axe.Result[]): string[] {
  return violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${violation.help} — ${node.target.join(" ")}`),
  );
}

beforeEach(() => {
  // axe probes a canvas for icon fonts; jsdom has none (and says so on stderr).
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

afterEach(() => {
  cleanup();
  act(() => resetToastStore());
});

for (const [component, stories] of Object.entries(MODULES)) {
  describe(`${component} stories`, () => {
    for (const [name, Story] of Object.entries(stories)) {
      it(`${name} passes axe`, async () => {
        render(<Story />);
        // Effects (toasts shown on mount, the drawer opening) and portals settle.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 0));
        });
        const results = await axe.run(document.body, OPTIONS);
        expect(describeViolations(results.violations)).toEqual([]);
      });
    }
  });
}

describe("the axe harness", () => {
  it("fails on a violation (an unnamed icon button)", async () => {
    render(
      <button type="button">
        <svg aria-hidden="true" />
      </button>,
    );
    const results = await axe.run(document.body, OPTIONS);
    expect(describeViolations(results.violations).join("\n")).toContain("button-name");
  });

  it("sees what the open stories portal into the body", async () => {
    const { Variants } = MODULES.Toast;
    const { Open } = MODULES.Modal;
    const { DrawerOpen } = MODULES.Layout;
    render(
      <>
        <Variants />
        <Open />
        <DrawerOpen />
      </>,
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(document.querySelectorAll("[data-variant]")).toHaveLength(4);
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(2);
  });
});
