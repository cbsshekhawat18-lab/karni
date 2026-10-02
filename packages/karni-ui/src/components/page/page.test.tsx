import { render, screen } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { Page } from "./page";

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
});
