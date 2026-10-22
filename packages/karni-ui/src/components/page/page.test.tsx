import { render, screen } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { Page, defaultPageSlots } from "./page";

describe("Page", () => {
  it("renders the title as the page h1 with description and children", () => {
    render(
      <Page title="Events" description="Everything scheduled">
        <p>Body content</p>
      </Page>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Events" })).toBeInTheDocument();
    expect(screen.getByText("Everything scheduled")).toBeInTheDocument();
    expect(screen.getByText("Body content")).toBeInTheDocument();
  });

  it("renders the actions slot next to the title", () => {
    render(<Page title="Events" actions={<button type="button">New event</button>} />);
    expect(screen.getByRole("button", { name: "New event" })).toBeInTheDocument();
  });

  it("omits the description paragraph when not given", () => {
    const { container } = render(<Page title="Events" />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("header slot replaces the derived title row (escape hatch)", () => {
    render(
      <Page title="Ignored" header={<div>Custom header</div>}>
        content
      </Page>,
    );
    expect(screen.getByText("Custom header")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ignored" })).not.toBeInTheDocument();
  });

  it("merges className and forwards arbitrary props and the ref", () => {
    const ref = React.createRef<HTMLElement>();
    render(<Page ref={ref} title="Events" className="max-w-4xl" data-testid="page-root" />);
    const root = screen.getByTestId("page-root");
    expect(root).toHaveClass("max-w-4xl");
    expect(ref.current).toBe(root);
  });

  it("slots replace the title, description, actions and header pieces", () => {
    render(
      <Page
        title="Events"
        description="All of them"
        actions={<button type="button">New</button>}
        slots={{
          Title: ({ children }) => <h2 data-testid="title">{children}</h2>,
          Description: ({ children }) => <em>{children}</em>,
          Actions: ({ children }) => <div data-testid="actions">{children}</div>,
          Header: (props) => (
            <div data-testid="header">
              <defaultPageSlots.Header {...props} />
            </div>
          ),
        }}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Events" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    expect(screen.getByText("All of them").tagName).toBe("EM");
    expect(screen.getByTestId("actions")).toContainElement(screen.getByRole("button"));
    expect(screen.getByTestId("header")).toContainElement(screen.getByTestId("title"));
  });
});
