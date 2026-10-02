import { describe, expect, it } from "vitest";
import {
  enumLabel,
  errorMessage,
  isNotFoundError,
  pageCountFor,
  sortingToOrdering,
} from "./table-utils";

describe("sortingToOrdering (D5: column ids are the ordering contract)", () => {
  it("maps asc/desc to DRF ordering values", () => {
    expect(sortingToOrdering([])).toBeUndefined();
    expect(sortingToOrdering([{ id: "title", desc: false }])).toBe("title");
    expect(sortingToOrdering([{ id: "title", desc: true }])).toBe("-title");
    expect(
      sortingToOrdering([
        { id: "status", desc: false },
        { id: "starts_at", desc: true },
      ]),
    ).toBe("status,-starts_at");
  });
});

describe("isNotFoundError", () => {
  it("duck-types a 404 status", () => {
    expect(isNotFoundError({ status: 404 })).toBe(true);
    expect(isNotFoundError({ status: 500 })).toBe(false);
    expect(isNotFoundError(new Error("boom"))).toBe(false);
    expect(isNotFoundError(null)).toBe(false);
    expect(isNotFoundError(undefined)).toBe(false);
  });
});

describe("pageCountFor", () => {
  it("rounds up and never drops below 1", () => {
    expect(pageCountFor(undefined, 25)).toBe(1);
    expect(pageCountFor(0, 25)).toBe(1);
    expect(pageCountFor(60, 25)).toBe(3);
    expect(pageCountFor(50, 25)).toBe(2);
    expect(pageCountFor(1, 25)).toBe(1);
  });
});

describe("errorMessage", () => {
  it("prefers DRF detail, then Error message, then a fallback", () => {
    expect(errorMessage({ data: { detail: "Invalid page." }, message: "x" })).toBe("Invalid page.");
    expect(errorMessage(new Error("Network down"))).toBe("Network down");
    expect(errorMessage("nope")).toBe("Something went wrong while loading this table.");
  });
});

describe("enumLabel", () => {
  it("prettifies constant-style members and leaves mixed case alone", () => {
    expect(enumLabel("DRAFT")).toBe("Draft");
    expect(enumLabel("in_progress")).toBe("In progress");
    expect(enumLabel("PUBLISHED")).toBe("Published");
    expect(enumLabel("iOS")).toBe("iOS");
    expect(enumLabel(3)).toBe("3");
  });
});
