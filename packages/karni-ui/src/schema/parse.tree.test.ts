/**
 * x-karni-tree (experimental): a tree resource, its tree operations, and the
 * relations that point at a tree, parsed from the simulated tree backend's
 * document (drf-spectacular dialect).
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
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

// The generated testapp snapshot, once it carries the tree models (Region,
// Category, Product): skipped until packages/karni's snapshot is copied here.

const SNAPSHOTS = ["schema.testapp.json", "schema.testapp.bigint.json"] as const;

describe.each(SNAPSHOTS)("x-karni-tree in the generated snapshot %s", (file) => {
  const path = join(process.cwd(), "tests", "fixtures", file);
  const text = existsSync(path) ? readFileSync(path, "utf8") : "";

  it.skipIf(!text.includes("x-karni-tree"))(
    "parses the testapp's tree resources and the relations that point at them " +
      "(no x-karni-tree yet? copy the snapshot from packages/karni tests/api/fixtures)",
    () => {
      const parsed = parseOpenApi(JSON.parse(text));
      const resources = Object.values(parsed.resources);
      const region = resources.find(
        (resource) => resource.tree !== undefined && resource.fields.some((f) => f.name === "code"),
      );
      const category = resources.find((resource) => resource.tree?.ordered === true);
      const product = resources.find((resource) =>
        resource.fields.some((field) => field.name === "category"),
      );
      expect(region?.tree).toEqual({ parent: "parent", ordered: false });
      expect(category?.tree).toEqual({ parent: "parent", ordered: true });
      for (const tree of [region, category]) {
        expect(tree?.operations.tree?.method).toBe("get");
        expect(tree?.operations.children?.method).toBe("get");
        expect(tree?.operations.ancestors?.method).toBe("get");
        expect(tree?.operations.move?.method).toBe("post");
        expect(tree?.operations.access?.method).toBe("get");
        const parent = tree?.fields.find((field) => field.name === "parent");
        expect(parent?.kind).toBe("relation");
        expect(parent?.tree).toBeDefined();
      }
      expect(category?.fields.find((field) => field.name === "position")?.readOnly).toBe(true);
      expect(product?.tree).toBeUndefined();
      expect(product?.operations.tree).toBeUndefined();
      expect(product?.operations.access).toBeUndefined();
      const fk = product?.fields.find((field) => field.name === "category");
      expect(fk?.relation?.many).toBe(false);
      expect(fk?.tree).toEqual({ parent: "parent", ordered: true });
      const m2m = product?.fields.find((field) => field.name === "regions");
      expect(m2m?.relation?.many).toBe(true);
      expect(m2m?.tree).toEqual({ parent: "parent", ordered: false });
    },
  );
});
