import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Modal, ModalClose, ModalTitle, defaultModalSlots } from "./modal";

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

  it("moves focus in, traps Tab, and returns focus to the trigger on Escape", async () => {
    const user = userEvent.setup();
    render(
      <Modal
        title="Edit event"
        trigger={<button type="button">Edit</button>}
        footer={<button type="button">Save</button>}
      >
        <input aria-label="Name" />
      </Modal>,
    );
    const trigger = screen.getByRole("button", { name: "Edit" });
    trigger.focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Edit event" });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    for (let i = 0; i < 4; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("slots replace the header, footer and close button", async () => {
    const user = userEvent.setup();
    render(
      <Modal
        title="Custom"
        description="Described"
        defaultOpen
        footer={<span>actions</span>}
        slots={{
          Header: ({ title }) => (
            <header data-testid="header">
              <ModalTitle>{title}!</ModalTitle>
            </header>
          ),
          Footer: ({ children }) => <footer data-testid="footer">{children}</footer>,
          CloseButton: ({ label }) => (
            <ModalClose asChild>
              <button type="button">{label} it</button>
            </ModalClose>
          ),
        }}
      />,
    );
    expect(screen.getByRole("dialog", { name: "Custom!" })).toBeInTheDocument();
    expect(screen.getByTestId("footer")).toHaveTextContent("actions");
    await user.click(screen.getByRole("button", { name: "Close it" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("exports its default slots for wrapping", () => {
    render(
      <Modal
        title="Wrapped"
        open
        slots={{
          Header: (props) => (
            <div data-testid="wrap">
              <defaultModalSlots.Header {...props} />
            </div>
          ),
        }}
      />,
    );
    expect(screen.getByTestId("wrap")).toHaveTextContent("Wrapped");
    expect(screen.getByRole("dialog", { name: "Wrapped" })).toBeInTheDocument();
  });
});
