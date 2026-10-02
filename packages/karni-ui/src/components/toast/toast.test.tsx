import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { resetToastStore, type ToastHandle } from "./toast-store";
import { Toaster } from "./toaster";
import { useToast, type UseToastResult } from "./use-toast";

/** Exposes the hook API to tests while <Toaster/> renders the toasts. */
function Harness(props: { onApi: (api: UseToastResult) => void }): React.ReactElement {
  const api = useToast();
  props.onApi(api);
  return <Toaster />;
}

function setup(): { api: () => UseToastResult; container: HTMLElement } {
  let latest: UseToastResult | null = null;
  const { container } = render(
    <Harness
      onApi={(api) => {
        latest = api;
      }}
    />,
  );
  return {
    api: () => {
      if (latest === null) {
        throw new Error("useToast API not captured");
      }
      return latest;
    },
    container,
  };
}

afterEach(() => {
  act(() => {
    resetToastStore();
  });
});

describe("Toaster + useToast", () => {
  it("success() renders a success-variant toast with title and description", () => {
    const { api, container } = setup();
    act(() => {
      api().success("Event saved", { description: "Your changes are live." });
    });

    const toast = container.querySelector('[data-variant="success"]');
    expect(toast).not.toBeNull();
    expect(toast).toHaveClass("border-primary");
    expect(screen.getAllByText("Event saved").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Your changes are live.").length).toBeGreaterThan(0);
  });

  it("error() uses the destructive tokens", () => {
    const { api, container } = setup();
    act(() => {
      api().error("Save failed");
    });

    const toast = container.querySelector('[data-variant="error"]');
    expect(toast).not.toBeNull();
    expect(toast).toHaveClass("bg-destructive");
  });

  it("info() renders the info variant", () => {
    const { api, container } = setup();
    act(() => {
      api().info("Heads up");
    });
    expect(container.querySelector('[data-variant="info"]')).not.toBeNull();
  });

  it("toast() accepts full options including an action slot", () => {
    const { api, container } = setup();
    act(() => {
      api().toast({
        title: "Deleted",
        variant: "default",
        action: <button type="button">Undo</button>,
      });
    });
    expect(container.querySelector('[data-variant="default"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("the close button dismisses the toast", async () => {
    const user = userEvent.setup();
    const { api, container } = setup();
    act(() => {
      api().info("Dismiss me");
    });

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(container.querySelector('[data-variant="info"]')).toBeNull();
    expect(api().toasts).toHaveLength(0);
  });

  it("the returned handle dismisses its own toast", () => {
    const { api, container } = setup();
    let handle: ToastHandle | null = null;
    act(() => {
      handle = api().success("Temporary");
    });
    expect(container.querySelector('[data-variant="success"]')).not.toBeNull();

    act(() => {
      handle?.dismiss();
    });
    expect(container.querySelector('[data-variant="success"]')).toBeNull();
  });

  it("dismiss() without an id clears every toast", () => {
    const { api } = setup();
    act(() => {
      api().info("one");
      api().info("two");
    });
    expect(api().toasts).toHaveLength(2);

    act(() => {
      api().dismiss();
    });
    expect(api().toasts).toHaveLength(0);
  });

  it("drops the oldest toast beyond the limit of five", () => {
    const { api } = setup();
    act(() => {
      for (let i = 1; i <= 6; i += 1) {
        api().info(`toast ${String(i)}`);
      }
    });
    expect(api().toasts).toHaveLength(5);
    expect(api().toasts[0]?.title).toBe("toast 2");
  });

  it("re-using an id replaces the toast instead of stacking", () => {
    const { api } = setup();
    act(() => {
      api().toast({ id: "progress", title: "Uploading" });
      api().toast({ id: "progress", title: "Uploaded" });
    });
    expect(api().toasts).toHaveLength(1);
    expect(api().toasts[0]?.title).toBe("Uploaded");
  });
});
