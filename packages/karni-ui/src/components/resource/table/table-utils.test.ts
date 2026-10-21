import { describe, expect, it } from "vitest";
import { KarniApiError } from "../../../schema/client";
import {
  enumLabel,
  errorMessage,
  isNotFoundError,
  orderingToSorting,
  pageCountFor,
  resourceWords,
  shouldRetryList,
  singular,
  sortingToOrdering,
} from "./table-utils";

describe("orderingToSorting", () => {
  it("is the inverse of sortingToOrdering", () => {
    expect(orderingToSorting("")).toEqual([]);
    expect(orderingToSorting("status,-starts_at")).toEqual([
      { id: "status", desc: false },
      { id: "starts_at", desc: true },
    ]);
    expect(sortingToOrdering(orderingToSorting("-title"))).toBe("-title");
  });
});

describe("shouldRetryList", () => {
  it("never retries a refusal (4xx) except a timeout or a rate limit", () => {
    for (const status of [400, 401, 403, 404, 409, 422]) {
      expect(shouldRetryList(0, new KarniApiError(status, {}))).toBe(false);
    }
    expect(shouldRetryList(0, new KarniApiError(408, {}))).toBe(true);
    expect(shouldRetryList(0, new KarniApiError(429, {}))).toBe(true);
    expect(shouldRetryList(0, new KarniApiError(503, {}))).toBe(true);
    expect(shouldRetryList(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetryList(3, new KarniApiError(503, {}))).toBe(false);
  });
});

describe("resource words", () => {
  it("names the resource as a sentence does, one and many", () => {
    expect(resourceWords("loose-slots")).toBe("loose slots");
    expect(singular("events")).toBe("event");
    expect(singular("categories")).toBe("category");
    expect(singular("addresses")).toBe("address");
    expect(singular("courses")).toBe("course");
    expect(singular("people")).toBe("people");
  });
});

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
