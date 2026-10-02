import { describe, expect, it } from "vitest";
import { displayLabel } from "../displayLabel";

describe("displayLabel (contract heuristic name→title→label→email→str→id)", () => {
  it("prefers name over title over label over email over str", () => {
    expect(displayLabel({ name: "Ada", title: "T", label: "L", email: "a@b.c" })).toBe("Ada");
    expect(displayLabel({ title: "T", label: "L" })).toBe("T");
    expect(displayLabel({ label: "L", email: "a@b.c" })).toBe("L");
    expect(displayLabel({ email: "a@b.c", id: 9 })).toBe("a@b.c");
    expect(displayLabel({ str: "Stringified", id: 9 })).toBe("Stringified");
  });

  it("skips empty and non-string candidates", () => {
    expect(displayLabel({ name: "", title: "   ", label: 42, email: "x@y.z" })).toBe("x@y.z");
  });

  it("falls back to String(id), then empty string", () => {
    expect(displayLabel({ id: 7 })).toBe("7");
    expect(displayLabel({ id: "ab-12" })).toBe("ab-12");
    expect(displayLabel({})).toBe("");
  });
});
