/**
 * EmptyValue — one rendering of "no value" across ResourceTable,
 * ResourceDetail and ChangeHistory: a muted dash, read as "empty".
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FieldDef } from "../../schema/types";
import { EmptyValue } from "./empty-value";
import { renderFieldCell } from "./table/derive-columns";

const text: FieldDef = {
  name: "description",
  label: "Description",
  kind: "text",
  required: false,
  readOnly: false,
  writeOnly: false,
  nullable: true,
  order: 0,
};

describe("EmptyValue", () => {
  it("shows a dash that screen readers read as 'empty'", () => {
    render(<EmptyValue />);
    expect(screen.getByText("–")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("empty")).toHaveClass("sr-only");
  });

  it("takes the word to read and merges className", () => {
    render(<EmptyValue label="not set" className="italic" data-testid="value" />);
    expect(screen.getByText("not set")).toHaveClass("sr-only");
    expect(screen.getByTestId("value")).toHaveClass("italic", "text-muted-foreground");
  });

  it("is what ResourceTable's cells render for null, undefined and an empty string", () => {
    for (const value of [null, undefined, ""]) {
      const { unmount } = render(<>{renderFieldCell(text, value)}</>);
      expect(screen.getByText("empty")).toBeInTheDocument();
      unmount();
    }
  });
});
