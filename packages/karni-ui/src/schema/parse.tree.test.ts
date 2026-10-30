/**
 * x-karni-tree (experimental): a tree resource, its tree operations, and the
 * relations that point at a tree, parsed from the simulated tree backend's
 * document (drf-spectacular dialect).
 */
import { describe, expect, it } from "vitest";
import { treeOpenApi } from "../components/resource/tree/tree-backend";
import { parseOpenApi, parseTreeExtension } from "./parse";

describe("x-karni-tree", () => {
  const parsed = parseOpenApi(treeOpenApi());

  it("marks a tree resource, ordered or not", () => {
    expect(parsed.resources.regions?.tree).toEqual({ parent: "parent", ordered: false });
    expect(parsed.resources.categories?.tree).toEqual({ parent: "parent", ordered: true });
    expect(parsed.resources.products?.tree).toBeUndefined();
  });

  it("finds the tree operations under the list and item paths", () => {
    const operations = parsed.resources.regions?.operations;
    expect(operations?.tree).toMatchObject({ path: "/api/regions/tree/", method: "get" });
    expect(operations?.tree?.queryParams).toEqual(["root", "depth"]);
    expect(operations?.children).toMatchObject({
      path: "/api/regions/{id}/children/",
      method: "get",
    });
    expect(operations?.ancestors).toMatchObject({ path: "/api/regions/{id}/ancestors/" });
    expect(operations?.move).toMatchObject({ path: "/api/regions/{id}/move/", method: "post" });
    // The detail operations still come from the item path, not the nested ones.
    expect(operations?.detail?.path).toBe("/api/regions/{id}/");
    expect(parsed.resources.products?.operations.tree).toBeUndefined();
  });

  it("marks every relation that points at a tree", () => {
    const fields = parsed.resources.products?.fields ?? [];
    const category = fields.find((field) => field.name === "category");
    const regions = fields.find((field) => field.name === "regions");
    expect(category).toMatchObject({
      kind: "relation",
      relation: { resource: "categories", many: false },
      tree: { parent: "parent", ordered: true },
    });
    expect(regions).toMatchObject({
      kind: "relation",
      relation: { resource: "regions", many: true },
      tree: { parent: "parent", ordered: false },
    });
    expect(fields.find((field) => field.name === "name")?.tree).toBeUndefined();
    // The parent field of a tree points at the tree itself.
    const parent = parsed.resources.regions?.fields.find((field) => field.name === "parent");
    expect(parent?.tree).toEqual({ parent: "parent", ordered: false });
  });

  it("keeps the position of an ordered tree read-only", () => {
    const position = parsed.resources.categories?.fields.find((field) => field.name === "position");
    expect(position?.readOnly).toBe(true);
  });

  it("reads the extension leniently", () => {
    expect(parseTreeExtension(true)).toEqual({ parent: "parent", ordered: false });
    expect(parseTreeExtension({ ordered: true })).toEqual({ parent: "parent", ordered: true });
    expect(parseTreeExtension({ parent: "up", ordered: "yes" })).toEqual({
      parent: "up",
      ordered: false,
    });
    expect(parseTreeExtension("tree")).toBeUndefined();
    expect(parseTreeExtension(undefined)).toBeUndefined();
  });
});
