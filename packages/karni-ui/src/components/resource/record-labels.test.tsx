/**
 * Rows named for people (SHARED piece 13): a relation shows the field its
 * model names rows by, a person shows their name, never an id, and a
 * registered record link turns the cell into a link to that record.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FieldDef } from "../../schema/types";
import { personName, relationLabel } from "./displayLabel";
import { registerRecordLink, setRecordNavigate, unregisterRecordLink } from "./record-links";
import { renderFieldCell } from "./table/derive-columns";

const order: FieldDef = {
  name: "order",
  label: "Order",
  kind: "relation",
  required: true,
  readOnly: false,
  writeOnly: false,
  nullable: false,
  order: 0,
  relation: { resource: "orders", many: false, label: "number" },
};

const buyer: FieldDef = {
  name: "user",
  label: "User",
  kind: "string",
  format: "uuid",
  required: false,
  readOnly: true,
  writeOnly: false,
  nullable: true,
  order: 1,
  person: true,
};

const expandedOrder = { id: "o-1", number: 1021, email: "mira@example.com" };

afterEach(() => {
  unregisterRecordLink("orders");
  setRecordNavigate(null);
});

describe("relationLabel and personName", () => {
  it("reads the field the target names its rows by, before any guess", () => {
    expect(relationLabel(order, expandedOrder)).toBe("1021");
    expect(relationLabel({ relation: {} }, expandedOrder)).toBe("mira@example.com");
  });

  it("names a person by their name, else their email", () => {
    expect(personName({ id: "u", first_name: "Mira", last_name: "Okafor", email: "m@x.io" })).toBe(
      "Mira Okafor",
    );
    expect(personName({ id: "u", first_name: "", email: "m@x.io" })).toBe("m@x.io");
  });
});

describe("relation and person cells", () => {
  it("shows the order's number, not the buyer's email", () => {
    render(<>{renderFieldCell(order, expandedOrder)}</>);
    expect(screen.getByText("1021")).toBeInTheDocument();
    expect(screen.queryByText("mira@example.com")).not.toBeInTheDocument();
  });

  it("shows an expanded person by name", () => {
    const person = { id: "u-1", first_name: "Theo", last_name: "Lindqvist", email: "t@x.io" };
    render(<>{renderFieldCell(buyer, person)}</>);
    expect(screen.getByText("Theo Lindqvist")).toBeInTheDocument();
  });

  it("links to the record when the app registered where it lives", () => {
    const go = vi.fn();
    registerRecordLink("orders", (row) => `/orders/${String(row.number)}`);
    setRecordNavigate(go);
    const rowClick = vi.fn();
    render(<div onClick={rowClick}>{renderFieldCell(order, expandedOrder)}</div>);
    const link = screen.getByRole("link", { name: "1021" });
    expect(link).toHaveAttribute("href", "/orders/1021");
    fireEvent.click(link);
    expect(go).toHaveBeenCalledWith("/orders/1021");
    expect(rowClick).not.toHaveBeenCalled();
  });
});
