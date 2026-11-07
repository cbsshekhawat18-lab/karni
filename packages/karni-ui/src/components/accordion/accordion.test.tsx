import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Accordion, toggleAccordion, type AccordionItem } from "./accordion";
import { axeViolations } from "../../../tests/axe";

const items: AccordionItem[] = [
  { id: "a", title: "Shipping", content: <p>Two days.</p> },
  { id: "b", title: "Returns", content: <p>Thirty days.</p> },
  { id: "c", title: "Archived", content: <p>Old.</p>, disabled: true },
  { id: "d", title: "Warranty", content: <p>Two years.</p> },
];

function trigger(name: string): HTMLElement {
  return screen.getByRole("button", { name });
}

describe("Accordion", () => {
  it("follows the WAI-ARIA pattern: a heading, a button that controls a named region", () => {
    render(<Accordion items={items} defaultOpen={["a"]} />);
    const button = trigger("Shipping");
    expect(button.closest("h3")).not.toBeNull();
    expect(button).toHaveAttribute("aria-expanded", "true");
    const region = document.getElementById(button.getAttribute("aria-controls") ?? "");
    expect(region).toHaveAttribute("role", "region");
    expect(screen.getByRole("region", { name: "Shipping" })).toHaveTextContent("Two days.");
    // A closed region is hidden: no tab stop, nothing read.
    expect(trigger("Returns")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Returns" })).not.toBeInTheDocument();
  });

  it("opens and closes on click, Enter and Space; several stay open by default", async () => {
    const user = userEvent.setup();
    render(<Accordion items={items} />);
    await user.click(trigger("Shipping"));
    trigger("Returns").focus();
    await user.keyboard("{Enter}");
    expect(trigger("Shipping")).toHaveAttribute("aria-expanded", "true");
    expect(trigger("Returns")).toHaveAttribute("aria-expanded", "true");
    await user.keyboard(" ");
    expect(trigger("Returns")).toHaveAttribute("aria-expanded", "false");
  });

  it("moves between headers with Down, Up, Home and End, skipping disabled ones", async () => {
    const user = userEvent.setup();
    render(<Accordion items={items} />);
    trigger("Returns").focus();
    await user.keyboard("{ArrowDown}");
    expect(trigger("Warranty")).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(trigger("Shipping")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(trigger("Warranty")).toHaveFocus();
    await user.keyboard("{Home}");
    expect(trigger("Shipping")).toHaveFocus();
    await user.keyboard("{End}");
    expect(trigger("Warranty")).toHaveFocus();
    expect(trigger("Archived")).toBeDisabled();
  });

  it("keeps one open with type single, and the last one open unless collapsible", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Accordion items={items} type="single" defaultOpen={["a"]} />);
    await user.click(trigger("Returns"));
    expect(trigger("Shipping")).toHaveAttribute("aria-expanded", "false");
    expect(trigger("Returns")).toHaveAttribute("aria-expanded", "true");
    await user.click(trigger("Returns"));
    expect(trigger("Returns")).toHaveAttribute("aria-expanded", "false");
    rerender(
      <Accordion
        key="locked"
        items={items}
        type="single"
        collapsible={false}
        defaultOpen={["a"]}
      />,
    );
    await user.click(trigger("Shipping"));
    expect(trigger("Shipping")).toHaveAttribute("aria-expanded", "true");
    expect(trigger("Shipping")).toHaveAttribute("aria-disabled", "true");
  });

  it("can be controlled, and its slot replaces how a header reads", async () => {
    const onOpenChange = vi.fn();
    render(
      <Accordion
        items={items}
        open={["b"]}
        onOpenChange={onOpenChange}
        slots={{
          Trigger: ({ item, open }) => (
            <span>{`${String(item.title)} (${open ? "open" : "closed"})`}</span>
          ),
        }}
      />,
    );
    await userEvent.click(trigger("Shipping (closed)"));
    expect(onOpenChange).toHaveBeenCalledWith(["b", "a"]);
    // Controlled: nothing changes until the parent passes a new `open`.
    expect(trigger("Shipping (closed)")).toHaveAttribute("aria-expanded", "false");
    expect(trigger("Returns (open)")).toHaveAttribute("aria-expanded", "true");
  });

  it("toggles by the accordion's rules", () => {
    expect(toggleAccordion(["a"], "b", "multiple", true)).toEqual(["a", "b"]);
    expect(toggleAccordion(["a", "b"], "a", "multiple", true)).toEqual(["b"]);
    expect(toggleAccordion(["a"], "b", "single", true)).toEqual(["b"]);
    expect(toggleAccordion(["a"], "a", "single", true)).toEqual([]);
    expect(toggleAccordion(["a"], "a", "single", false)).toEqual(["a"]);
  });

  it("passes axe, open and closed", async () => {
    const { container } = render(<Accordion items={items} defaultOpen={["a", "d"]} />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
