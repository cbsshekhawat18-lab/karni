/**
 * Numbers in ResourceDetail and ResourceTable: grouped for the locale, except
 * an id (integer keys, BigIntBaseModel), which reads as it is written in a URL.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FieldDef } from "../../schema/types";
import { formatMoney } from "../../lib/money";
import { parseMoneyExtension } from "../../schema/parse";
import { formatMoneyValue, formatNumberValue } from "./number-value";
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

describe("years and money", () => {
  it("leaves a year without separators", () => {
    expect(formatNumberValue(integer("year"), 2024)).toBe("2024");
    expect(formatNumberValue(integer("founded_year"), 1998)).toBe("1998");
    expect(formatNumberValue(integer("number"), 1027)).toBe("1027");
    expect(formatNumberValue(integer("invoice_number"), 20261)).toBe("20261");
  });

  it("shows money in its fixed currency, or the row's, and nothing it cannot know", () => {
    const price: FieldDef = { ...integer("price"), kind: "text", money: { currency: "EUR" } };
    const total: FieldDef = {
      ...integer("total"),
      kind: "text",
      money: { currencyField: "currency" },
    };
    expect(formatMoneyValue(price, "60.0000")).toBe(formatMoney("60.0000", "EUR"));
    expect(formatMoneyValue(total, "12.5000", { currency: "USD" })).toBe(
      formatMoney("12.5000", "USD"),
    );
    expect(formatMoneyValue(total, "12.5000", {})).toBeNull();
    expect(formatMoneyValue(integer("count"), 3)).toBeNull();
    render(<>{renderFieldCell(total, "1234.5000", undefined, { currency: "USD" })}</>);
    expect(screen.getByText(formatMoney("1234.5", "USD"))).toBeInTheDocument();
  });
});

describe("x-karni-money", () => {
  it("reads a fixed currency or a currency field, and nothing else", () => {
    expect(parseMoneyExtension({ currency: "EUR" })).toEqual({ currency: "EUR" });
    expect(parseMoneyExtension({ currency_field: "currency" })).toEqual({
      currencyField: "currency",
    });
    expect(parseMoneyExtension({})).toBeUndefined();
    expect(parseMoneyExtension("EUR")).toBeUndefined();
  });
});
