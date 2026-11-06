/**
 * Importing the package makes @karni/ui's ResourceDetail and ResourceTable show
 * a protected file field (`x-karni-storage`, `protected: true`) with ProtectedFileLink.
 */

import { protectedFileLinkFor, type FieldDef } from "@karni/ui";
import { describe, expect, it } from "vitest";
import { ProtectedFileLink } from "./ProtectedFileLink";
import "./index";

const field: FieldDef = {
  name: "manual",
  label: "Manual",
  kind: "file",
  order: 0,
  required: false,
  readOnly: false,
  writeOnly: false,
  nullable: true,
  protected: true,
};

describe("registration", () => {
  it("registers ProtectedFileLink for protected fields only", () => {
    expect(protectedFileLinkFor(field)).toBe(ProtectedFileLink);
    const { protected: _unused, ...plain } = field;
    expect(protectedFileLinkFor(plain)).toBeNull();
  });
});
