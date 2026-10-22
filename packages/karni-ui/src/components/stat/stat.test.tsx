import { render, screen } from "@testing-library/react";
import * as React from "react";
import { describe, expect, it } from "vitest";
import { Stat, defaultStatSlots, type StatDeltaProps } from "./stat";

describe("Stat", () => {
  it("renders label and value", () => {
    render(<Stat label="Active users" value="1,284" />);
    expect(screen.getByText("Active users")).toBeInTheDocument();
    expect(screen.getByText("1,284")).toBeInTheDocument();
  });

  it("renders a positive numeric delta with increase context", () => {
    render(<Stat label="Signups" value={420} delta={12} />);
    expect(screen.getByText("+12")).toBeInTheDocument();
    expect(screen.getByText(/increased by/i)).toBeInTheDocument();
  });

  it("renders a negative numeric delta with the destructive token and decrease context", () => {
    render(<Stat label="Signups" value={420} delta={-3} />);
    const delta = screen.getByText("-3");
    expect(delta.closest("p")).toHaveClass("text-destructive");
    expect(screen.getByText(/decreased by/i)).toBeInTheDocument();
  });

  it("formatDelta overrides numeric formatting (escape hatch)", () => {
    render(<Stat label="Churn" value="2%" delta={5} formatDelta={(d) => `${String(d)} pts`} />);
    expect(screen.getByText("5 pts")).toBeInTheDocument();
  });

  it("renders a non-numeric delta verbatim", () => {
    render(<Stat label="Uptime" value="99.9%" delta={<em>steady</em>} />);
    expect(screen.getByText("steady")).toBeInTheDocument();
    expect(screen.queryByText(/increased by/i)).not.toBeInTheDocument();
  });

  it("renders the icon slot aria-hidden", () => {
    render(<Stat label="Revenue" value="$10k" icon={<svg data-testid="stat-icon" />} />);
    expect(screen.getByTestId("stat-icon").parentElement).toHaveAttribute("aria-hidden", "true");
  });

  it("merges className and forwards the ref", () => {
    const ref = React.createRef<HTMLDivElement>();
    render(<Stat ref={ref} label="A" value="B" className="w-64" data-testid="stat-root" />);
    const root = screen.getByTestId("stat-root");
    expect(root).toHaveClass("w-64");
    expect(ref.current).toBe(root);
  });

  it("says a zero delta is unchanged instead of an increase", () => {
    render(<Stat label="Signups" value={420} delta={0} />);
    expect(screen.getByText(/unchanged/i)).toBeInTheDocument();
    expect(screen.queryByText(/increased by/i)).not.toBeInTheDocument();
    expect(screen.getByText("0").closest("p")).toHaveAttribute("data-trend", "flat");
  });

  it("shows a placeholder and is busy while loading", () => {
    render(<Stat label="Revenue" value="$10k" delta={4} loading data-testid="stat" />);
    expect(screen.getByTestId("stat")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.queryByText("$10k")).not.toBeInTheDocument();
    expect(screen.queryByText(/increased by/i)).not.toBeInTheDocument();
    expect(screen.getByText("Loading")).toHaveClass("sr-only");
  });

  it("slots replace the label, value, delta and icon", () => {
    function GoodWhenDown({ delta, formatDelta }: StatDeltaProps) {
      return typeof delta === "number" ? (
        <p data-testid="delta">{formatDelta(delta)} (good)</p>
      ) : null;
    }
    render(
      <Stat
        label="Churn"
        value="2%"
        delta={-1}
        icon={<svg data-testid="icon" />}
        slots={{
          Label: ({ children }) => <h3>{children}</h3>,
          Value: ({ children }) => <strong>{children}</strong>,
          Delta: GoodWhenDown,
          Icon: ({ children }) => (
            <span data-testid="icon-slot">
              <defaultStatSlots.Icon>{children}</defaultStatSlots.Icon>
            </span>
          ),
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Churn" })).toBeInTheDocument();
    expect(screen.getByText("2%").tagName).toBe("STRONG");
    expect(screen.getByTestId("delta")).toHaveTextContent("-1 (good)");
    expect(screen.getByTestId("icon-slot")).toContainElement(screen.getByTestId("icon"));
  });
});
