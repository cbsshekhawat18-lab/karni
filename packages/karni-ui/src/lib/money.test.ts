import { describe, expect, it } from "vitest";
import { formatMoney } from "./money";

describe("formatMoney", () => {
  it("rounds the API's four places to the currency's digits", () => {
    expect(formatMoney("1234.5000", "usd", "en-US")).toBe("$1,234.50");
    expect(formatMoney(60, "EUR", "en-GB")).toBe("€60.00");
    expect(formatMoney("500", "JPY", "en-US")).toBe("¥500");
  });

  it("keeps what is not a number, and empties nothing", () => {
    expect(formatMoney("n/a", "USD")).toBe("n/a");
    expect(formatMoney(null, "USD")).toBe("");
    expect(formatMoney("", "USD")).toBe("");
  });

  it("falls back for a currency the browser does not know", () => {
    expect(formatMoney("3.5", "XX", "en-US")).toBe("3.50 XX");
  });
});
