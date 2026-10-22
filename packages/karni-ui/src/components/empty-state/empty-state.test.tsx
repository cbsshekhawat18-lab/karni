import { render, screen } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { EmptyState, defaultEmptyStateSlots } from "./empty-state";

describe("EmptyState", () => {
  it("renders title, description and the action slot", () => {
    render(
      <EmptyState
        title="No events yet"
        description="Create your first event to get started."
        action={<button type="button">Create event</button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "No events yet" })).toBeInTheDocument();
    expect(screen.getByText("Create your first event to get started.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create event" })).toBeInTheDocument();
  });

  it("renders the icon slot aria-hidden", () => {
    render(<EmptyState title="Empty" icon={<svg data-testid="empty-icon" />} />);
    const icon = screen.getByTestId("empty-icon");
    expect(icon.parentElement).toHaveAttribute("aria-hidden", "true");
  });

  it("renders without optional parts", () => {
    render(<EmptyState title="Empty" />);
    expect(screen.getByText("Empty")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("merges className and forwards the ref (escape hatch)", () => {
    const ref = React.createRef<HTMLDivElement>();
    render(<EmptyState ref={ref} title="Empty" className="py-24" data-testid="empty-root" />);
    const root = screen.getByTestId("empty-root");
    expect(root).toHaveClass("py-24");
    expect(ref.current).toBe(root);
  });

  it("slots replace the icon, title, description and actions", () => {
    render(
      <EmptyState
        icon={<svg data-testid="icon" />}
        title="No events"
        description="Nothing scheduled"
        action={<button type="button">Create</button>}
        slots={{
          Icon: ({ children }) => <span data-testid="icon-slot">{children}</span>,
          Title: ({ children }) => <h2>{children}</h2>,
          Description: ({ children }) => (
            <defaultEmptyStateSlots.Description>
              <strong>{children}</strong>
            </defaultEmptyStateSlots.Description>
          ),
          Actions: ({ children }) => <footer data-testid="actions">{children}</footer>,
        }}
      />,
    );
    expect(screen.getByTestId("icon-slot")).toContainElement(screen.getByTestId("icon"));
    expect(screen.getByRole("heading", { level: 2, name: "No events" })).toBeInTheDocument();
    expect(screen.getByText("Nothing scheduled").tagName).toBe("STRONG");
    expect(screen.getByTestId("actions")).toContainElement(screen.getByRole("button"));
  });
});
