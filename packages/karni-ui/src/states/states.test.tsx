import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KarniApiError } from "../schema/client";
import { ErrorState, PermissionDenied } from "./ErrorState";
import { PendingButton } from "./PendingButton";

afterEach(() => vi.useRealTimers());

describe("ErrorState", () => {
  it("says what failed in plain words and offers a retry when it can help", async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new KarniApiError(503, {})} onRetry={onRetry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    expect(alert).not.toHaveTextContent("503");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("offers no retry for a permission error", () => {
    render(
      <ErrorState
        error={new KarniApiError(403, {})}
        context={{ action: "export", resource: "bookings" }}
        onRetry={() => undefined}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("You can't export bookings");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

describe("PermissionDenied", () => {
  it("names the action that is not allowed", () => {
    render(<PermissionDenied action="create" resource="events" />);
    expect(screen.getByText("You can't create events")).toBeInTheDocument();
  });
});

describe("PendingButton", () => {
  it("disables at once and shows progress only once the work is slow", () => {
    vi.useFakeTimers();
    const { rerender } = render(<PendingButton>Save</PendingButton>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeEnabled();
    rerender(
      <PendingButton pending pendingLabel="Saving…">
        Save
      </PendingButton>,
    );
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector("svg")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Saving…");
    act(() => vi.advanceTimersByTime(500));
    expect(button.querySelector("svg")).not.toBeNull();
    // The label stays in the layout (hidden), so the button keeps its width.
    expect(screen.getByText("Save")).toHaveClass("text-transparent");
    rerender(<PendingButton>Save</PendingButton>);
    expect(button).toBeEnabled();
    expect(button.querySelector("svg")).toBeNull();
  });
});
