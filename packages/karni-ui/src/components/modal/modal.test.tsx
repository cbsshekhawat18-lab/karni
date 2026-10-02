import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Modal, ModalClose } from "./modal";

describe("Modal", () => {
  it("opens from the trigger slot and labels the dialog with the title", async () => {
    const user = userEvent.setup();
    render(
      <Modal
        title="Delete event"
        description="This cannot be undone."
        trigger={<button type="button">Delete</button>}
      >
        <p>Body</p>
      </Modal>,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    const dialog = screen.getByRole("dialog", { name: "Delete event" });
    expect(dialog).toHaveAccessibleDescription("This cannot be undone.");
    expect(screen.getByText("Body")).toBeInTheDocument();
  });

  it("works controlled: renders when open and reports close requests", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <Modal title="Settings" open onOpenChange={onOpenChange}>
        <p>Form</p>
      </Modal>,
    );

    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<Modal title="Settings" open onOpenChange={onOpenChange} />);

    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("renders the footer slot and ModalClose closes the dialog", async () => {
    const user = userEvent.setup();
    render(
      <Modal
        title="Confirm"
        defaultOpen
        footer={
          <ModalClose asChild>
            <button type="button">Cancel</button>
          </ModalClose>
        }
      />,
    );

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("hides the X button with hideCloseButton", () => {
    render(<Modal title="Plain" open hideCloseButton />);
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  });

  it("has no aria-describedby without a description", () => {
    render(<Modal title="Plain" open />);
    expect(screen.getByRole("dialog")).not.toHaveAttribute("aria-describedby");
  });

  it("contentProps reach the Radix content part (escape hatch)", async () => {
    const user = userEvent.setup();
    const onEscapeKeyDown = vi.fn((event: KeyboardEvent) => {
      event.preventDefault();
    });
    render(<Modal title="Sticky" open contentProps={{ onEscapeKeyDown }} />);

    await user.keyboard("{Escape}");
    expect(onEscapeKeyDown).toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
