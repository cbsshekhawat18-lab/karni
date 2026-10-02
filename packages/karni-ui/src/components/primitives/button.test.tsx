import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { Button, buttonVariants } from "./button";

describe("Button", () => {
  it("renders its children and defaults type to button", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "button");
  });

  it("respects an explicit type", () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByRole("button", { name: "Submit" })).toHaveAttribute("type", "submit");
  });

  it("applies variant and size classes", () => {
    render(
      <Button variant="destructive" size="sm">
        Delete
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.className).toContain("bg-destructive");
    expect(button.className).toContain("h-9");
  });

  it("merges consumer className through cn() so consumer classes win", () => {
    render(<Button className="bg-accent">Styled</Button>);
    const button = screen.getByRole("button", { name: "Styled" });
    expect(button.className).toContain("bg-accent");
    // tailwind-merge drops the conflicting default bg-primary
    expect(button.className.split(/\s+/)).not.toContain("bg-primary");
  });

  it("forwards its ref to the underlying button element", () => {
    const ref = React.createRef<HTMLButtonElement>();
    render(<Button ref={ref}>Ref</Button>);
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });

  it("fires onClick, and not when disabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Go</Button>);
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(
      <Button onClick={onClick} disabled>
        Go
      </Button>,
    );
    expect(screen.getByRole("button", { name: "Go" })).toBeDisabled();
  });

  it("exposes buttonVariants as a composition escape hatch", () => {
    const classes = buttonVariants({ variant: "outline", className: "w-full" });
    expect(classes).toContain("border-input");
    expect(classes).toContain("w-full");
  });
});
