import { describe, expect, it } from "vitest";
import { evaluateAccess, type AccessIdentity } from "./access";

const ada: AccessIdentity = {
  status: "authenticated",
  user: { id: 7, email: "ada@example.com", roles: ["viewer"] },
};
const anonymous: AccessIdentity = { status: "anonymous", user: null };

describe("evaluateAccess (x-karni-access, a display hint)", () => {
  it("answers the predicates the client can evaluate", () => {
    expect(evaluateAccess({ public: true }, anonymous)).toBe(true);
    expect(evaluateAccess({ deny: "no access declared" }, ada)).toBe(false);
    expect(evaluateAccess({ authenticated: true }, ada)).toBe(true);
    expect(evaluateAccess({ authenticated: true }, anonymous)).toBe(false);
    expect(evaluateAccess({ role: ["staff", "viewer"] }, ada)).toBe(true);
    expect(evaluateAccess({ role: ["staff"] }, ada)).toBe(false);
    expect(evaluateAccess({ role: ["staff"] }, anonymous)).toBe(false);
  });

  it("checks Owned against the row's owner field, expanded or not", () => {
    const rule = { owned: "organizer" };
    expect(evaluateAccess(rule, ada, { organizer: 7 })).toBe(true);
    expect(evaluateAccess(rule, ada, { organizer: { id: 7, name: "Ada" } })).toBe(true);
    expect(evaluateAccess(rule, ada, { organizer: 8 })).toBe(false);
    expect(evaluateAccess({ owned: "members" }, ada, { members: [3, 7] })).toBe(true);
    expect(evaluateAccess(rule, anonymous, { organizer: 7 })).toBe(false);
    // The field is hidden from the role, or a traversal: only the server knows.
    expect(evaluateAccess(rule, ada, { title: "x" })).toBeUndefined();
    expect(evaluateAccess({ owned: "event__organizer" }, ada, { event: 1 })).toBeUndefined();
  });

  it("combines any / all three-valued", () => {
    const ownedOrStaff = { any: [{ owned: "organizer" }, { role: ["staff"] }] };
    expect(evaluateAccess(ownedOrStaff, ada, { organizer: 7 })).toBe(true);
    expect(evaluateAccess(ownedOrStaff, ada, { organizer: 8 })).toBe(false);
    expect(evaluateAccess({ any: [{ role: ["staff"] }, { can: ["x.y:change"] }] }, ada)).toBe(
      undefined,
    );
    expect(evaluateAccess({ all: [{ authenticated: true }, { role: ["staff"] }] }, ada)).toBe(
      false,
    );
    expect(evaluateAccess({ all: [{ authenticated: true }, { granted: true }] }, ada)).toBe(
      undefined,
    );
  });

  it("leaves to the server what only it can answer", () => {
    expect(evaluateAccess(undefined, ada)).toBeUndefined();
    expect(evaluateAccess({ can: ["events.event:change"] }, ada)).toBeUndefined();
    expect(evaluateAccess({ granted: true }, ada)).toBeUndefined();
    expect(evaluateAccess({ where: "published_only" }, ada)).toBeUndefined();
    // No AuthProvider, or the session is still loading.
    expect(evaluateAccess({ role: ["staff"] }, null)).toBeUndefined();
    expect(evaluateAccess({ authenticated: true }, { status: "loading", user: null })).toBe(
      undefined,
    );
  });
});
