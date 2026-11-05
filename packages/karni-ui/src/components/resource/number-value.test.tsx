/**
 * Numbers in ResourceDetail and ResourceTable: grouped for the locale, except
 * an id (integer keys, BigIntBaseModel), which reads as it is written in a URL.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FieldDef } from "../../schema/types";
import { formatNumberValue } from "./number-value";
import { renderFieldCell } from "./table/derive-columns";

function integer(name: string): FieldDef {
  return {
    name,
    label: name,
    kind: "integer",
    required: false,
    readOnly: true,
    writeOnly: false,
    nullable: false,
    order: 0,
  };
}

describe("formatNumberValue", () => {
  it("leaves an id without separators", () => {
    expect(formatNumberValue(integer("id"), 1234567)).toBe("1234567");
  });

  it("groups any other number for the locale", () => {
    expect(formatNumberValue(integer("capacity"), 1234567)).toBe((1234567).toLocaleString());
  });
});

describe("renderFieldCell", () => {
  it("shows an integer id as written and a count grouped", () => {
    render(
      <>
        {renderFieldCell(integer("id"), 9876543)}
        {renderFieldCell(integer("capacity"), 9876543)}
      </>,
    );
    expect(screen.getByText("9876543")).toBeInTheDocument();
    expect(screen.getByText((9876543).toLocaleString())).toBeInTheDocument();
  });
});
