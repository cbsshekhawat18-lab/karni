/**
 * A simulated Karni backend for the tree components' tests and stories: two
 * tree resources, `regions` (siblings in creation order) and `categories`
 * (ordered siblings), and `products`, which points at both (an FK
 * `category` and an M2M `regions`). It serves the OpenAPI document with
 * `x-karni-tree`, the list (with `?search=`, `?parent=` and
 * `?descendants_of=`), `tree/`, `children/`, `ancestors/`, `move/`,
 * `access/` (the requester's access forest) and the delete rules of a tree
 * model, plus failures and delays on demand. Every request is logged. With
 * `taxonomy: true`, `regions` is a taxonomy of `products` (`class Karni:
 * taxonomies`): `x-karni-taxonomy`, the list filters `?regions=` and
 * `?regions_descendants=` and `facets/` (with `?rollup=`).
 *
 * Test and story support only: never imported by shipped component code.
 */
import { delay, http, HttpResponse, type RequestHandler } from "msw";

export interface TreeRow {
  id: number;
  name: string;
  parent: number | null;
  /** Sibling order (categories only). */
  position?: number;
  deleted?: boolean;
}

export interface ProductRow {
  id: number;
  name: string;
  category: number | null;
  regions: number[];
}

/** A small region tree: three continents, countries below them, a city below one. */
export function makeRegions(): TreeRow[] {
  return [
    { id: 1, name: "Europe", parent: null },
    { id: 2, name: "Nordics", parent: 1 },
    { id: 3, name: "Norway", parent: 2 },
    { id: 4, name: "Sweden", parent: 2 },
    { id: 5, name: "Iberia", parent: 1 },
    { id: 6, name: "Portugal", parent: 5 },
    { id: 7, name: "Spain", parent: 5 },
    { id: 8, name: "Asia", parent: null },
    { id: 9, name: "Japan", parent: 8 },
    { id: 10, name: "Kyoto", parent: 9 },
    { id: 11, name: "Americas", parent: null },
    { id: 12, name: "Canada", parent: 11 },
  ];
}

/** A product catalog's ordered category tree. */
export function makeCategories(): TreeRow[] {
  return [
    { id: 1, name: "Garden", parent: null, position: 0 },
    { id: 2, name: "Tools", parent: 1, position: 0 },
    { id: 3, name: "Seeds", parent: 1, position: 1 },
    { id: 4, name: "Kitchen", parent: null, position: 1 },
    { id: 5, name: "Knives", parent: 4, position: 0 },
  ];
}

/**
 * A large tree: `roots` roots, each with `fanout` children per level, `levels`
 * levels deep. `makeWideTree(10, 10, 3)` has 10 + 100 + 1,000 = 1,110 nodes,
 * and `makeWideTree(10, 32, 3)` 10,570.
 */
export function makeWideTree(roots: number, fanout: number, levels: number): TreeRow[] {
  const rows: TreeRow[] = [];
  let next = 1;
  let layer: TreeRow[] = [];
  for (let index = 0; index < roots; index += 1) {
    const row = { id: next, name: `Area ${next}`, parent: null };
    next += 1;
    rows.push(row);
    layer.push(row);
  }
  for (let level = 1; level < levels; level += 1) {
    const below: TreeRow[] = [];
    for (const parent of layer) {
      for (let index = 0; index < fanout; index += 1) {
        const row = { id: next, name: `${parent.name}.${index + 1}`, parent: parent.id };
        next += 1;
        rows.push(row);
        below.push(row);
      }
    }
    layer = below;
  }
  return rows;
}

export type Failure = number | "offline";
export type Delay = number | "infinite";

export interface TreeBackendOptions {
  /** The region rows. Default `makeRegions()`. */
  regions?: TreeRow[];
  /** The category rows. Default `makeCategories()`. */
  categories?: TreeRow[];
  products?: ProductRow[];
  /** The tree/ node limit. Default 1000. */
  maxNodes?: number;
  /** Fail every tree/ request (any resource). */
  treeFailure?: Failure;
  /** Fail tree/ requests that name a root (lazy loads). */
  lazyFailure?: Failure;
  /** Fail ancestors/ requests. */
  ancestorsFailure?: Failure;
  /** Delay ancestors/ requests. */
  ancestorsDelay?: Delay;
  /** Delay every tree/ request. */
  treeDelay?: Delay;
  /** Delay tree/ requests that name a root. */
  lazyDelay?: Delay;
  /** Whether the region list documents `?search=`. Default true. */
  search?: boolean;
  /** The ids each resource's `access/` answers as granted. Default none. */
  granted?: Partial<Record<"regions" | "categories", number[]>>;
  /** `access/` answers `all: true`: the requester reaches every node. */
  accessAll?: boolean;
  /** `regions` is a taxonomy of `products`: its filters and `facets/`. Default false. */
  taxonomy?: boolean;
  /** Fail every facets/ request. */
  facetsFailure?: Failure;
}

export interface TreeBackend {
  handlers: RequestHandler[];
  /** Every request, in order. */
  requests: URL[];
  regions: TreeRow[];
  categories: TreeRow[];
  products: ProductRow[];
  /** The bodies of POST and PATCH requests, in order. */
  bodies: Array<{ url: URL; body: unknown }>;
  /** The tree/ requests only. */
  treeRequests: (resource?: string) => URL[];
}

function query(name: string, type: string): Record<string, unknown> {
  return { in: "query", name, required: false, schema: { type } };
}

function json(ref: string): Record<string, unknown> {
  return { "application/json": { schema: { $ref: `#/components/schemas/${ref}` } } };
}

function ok(ref: string): Record<string, unknown> {
  return { "200": { description: "", content: json(ref) } };
}

const idParam = { in: "path", name: "id", required: true, schema: { type: "integer" } };

function treePaths(resource: string, component: string, search: boolean): Record<string, unknown> {
  const base = `/api/${resource}/`;
  return {
    [base]: {
      get: {
        operationId: `${resource}_list`,
        "x-karni-resource": resource,
        parameters: [
          query("descendants_of", "integer"),
          query("ordering", "string"),
          query("page", "integer"),
          query("page_size", "integer"),
          query("parent", "string"),
          ...(search ? [query("search", "string")] : []),
        ],
        responses: ok(`Paginated${component}List`),
      },
      post: {
        operationId: `${resource}_create`,
        requestBody: { content: json(`${component}Request`) },
        responses: { "201": { description: "", content: json(component) } },
      },
    },
    [`${base}tree/`]: {
      get: {
        operationId: `${resource}_tree_retrieve`,
        parameters: [query("root", "string"), query("depth", "integer")],
        responses: ok(`${component}Tree`),
      },
    },
    [`${base}{id}/`]: {
      get: { operationId: `${resource}_retrieve`, parameters: [idParam], responses: ok(component) },
      patch: {
        operationId: `${resource}_partial_update`,
        parameters: [idParam],
        requestBody: { content: json(`Patched${component}Request`) },
        responses: ok(component),
      },
      delete: {
        operationId: `${resource}_destroy`,
        parameters: [idParam],
        responses: { "204": { description: "" } },
      },
    },
    [`${base}{id}/children/`]: {
      get: {
        operationId: `${resource}_children_list`,
        parameters: [idParam, query("page", "integer"), query("page_size", "integer")],
        responses: ok(`Paginated${component}TreeNodeList`),
      },
    },
    [`${base}{id}/ancestors/`]: {
      get: {
        operationId: `${resource}_ancestors_list`,
        parameters: [idParam],
        responses: {
          "200": {
            description: "",
            content: {
              "application/json": {
                schema: {
                  type: "array",
                  items: { $ref: `#/components/schemas/${component}TreeNode` },
                },
              },
            },
          },
        },
      },
    },
    [`${base}{id}/move/`]: {
      post: {
        operationId: `${resource}_move_create`,
        parameters: [idParam],
        requestBody: { content: json(`${component}MoveRequest`) },
        responses: ok(`${component}TreeNode`),
      },
    },
  };
}

function treeComponents(
  component: string,
  resource: string,
  ordered: boolean,
): Record<string, unknown> {
  const tree = { parent: "parent", ordered };
  const parent = {
    type: "integer",
    nullable: true,
    "x-karni-relation": { resource, many: false },
    "x-karni-tree": tree,
  };
  const row = {
    type: "object",
    required: ["id", "name"],
    "x-karni-tree": tree,
    properties: {
      id: { type: "integer", readOnly: true },
      name: { type: "string", maxLength: 100 },
      parent,
      ...(ordered ? { position: { type: "integer", readOnly: true } } : {}),
    },
  };
  const request = {
    type: "object",
    required: ["name"],
    properties: { name: { type: "string", maxLength: 100, minLength: 1 }, parent },
  };
  const node = {
    allOf: [{ $ref: `#/components/schemas/${component}` }],
    type: "object",
    properties: {
      has_children: { type: "boolean", readOnly: true },
      children: {
        type: "array",
        nullable: true,
        readOnly: true,
        items: { $ref: `#/components/schemas/${component}TreeNode` },
      },
    },
  };
  return {
    [component]: row,
    [`${component}Request`]: request,
    [`Patched${component}Request`]: { ...request, required: [] },
    [`${component}TreeNode`]: node,
    [`${component}Tree`]: {
      type: "object",
      properties: {
        results: { type: "array", items: { $ref: `#/components/schemas/${component}TreeNode` } },
        truncated: { type: "boolean" },
      },
    },
    [`${component}MoveRequest`]: {
      type: "object",
      properties: { parent: { type: "integer", nullable: true }, position: { type: "integer" } },
    },
    [`Paginated${component}List`]: paginated(component),
    [`Paginated${component}TreeNodeList`]: paginated(`${component}TreeNode`),
  };
}

function paginated(component: string): Record<string, unknown> {
  return {
    type: "object",
    required: ["count", "results"],
    properties: {
      count: { type: "integer" },
      next: { type: "string", nullable: true, format: "uri" },
      previous: { type: "string", nullable: true, format: "uri" },
      results: { type: "array", items: { $ref: `#/components/schemas/${component}` } },
    },
  };
}

/** The OpenAPI document of the simulated backend (drf-spectacular dialect). */
export function treeOpenApi(options: Pick<TreeBackendOptions, "search" | "taxonomy"> = {}) {
  const { search = true, taxonomy = false } = options;
  const product = {
    type: "object",
    required: ["id", "name"],
    properties: {
      id: { type: "integer", readOnly: true },
      name: { type: "string", maxLength: 100 },
      category: {
        type: "integer",
        nullable: true,
        "x-karni-relation": { resource: "categories", many: false },
        "x-karni-tree": { parent: "parent", ordered: true },
      },
      regions: {
        type: "array",
        items: { type: "integer" },
        "x-karni-relation": { resource: "regions", many: true },
        "x-karni-tree": { parent: "parent", ordered: false },
        ...(taxonomy ? { "x-karni-taxonomy": "regions" } : {}),
      },
    },
  };
  const taxonomyParams = taxonomy
    ? [query("regions", "string"), query("regions_descendants", "boolean")]
    : [];
  const facetsPath = taxonomy
    ? {
        "/api/products/facets/": {
          get: {
            operationId: "products_facets_retrieve",
            parameters: [
              { ...query("taxonomy", "string"), schema: { type: "string", enum: ["regions"] } },
              query("rollup", "boolean"),
              ...taxonomyParams,
              query("search", "string"),
            ],
            responses: ok("ProductFacets"),
          },
        },
      }
    : {};
  const productRequest = {
    type: "object",
    required: ["name"],
    properties: {
      name: { type: "string", maxLength: 100, minLength: 1 },
      category: product.properties.category,
      regions: product.properties.regions,
    },
  };
  return {
    openapi: "3.0.3",
    info: { title: "Catalog", version: "1.0.0" },
    "x-karni-auth-mode": "jwt",
    paths: {
      ...treePaths("regions", "Region", search),
      ...treePaths("categories", "Category", true),
      "/api/products/": {
        get: {
          operationId: "products_list",
          "x-karni-resource": "products",
          parameters: [query("page", "integer"), ...taxonomyParams, query("search", "string")],
          responses: ok("PaginatedProductList"),
        },
        post: {
          operationId: "products_create",
          requestBody: { content: json("ProductRequest") },
          responses: { "201": { description: "", content: json("Product") } },
        },
      },
      "/api/products/{id}/": {
        get: { operationId: "products_retrieve", parameters: [idParam], responses: ok("Product") },
        patch: {
          operationId: "products_partial_update",
          parameters: [idParam],
          requestBody: { content: json("PatchedProductRequest") },
          responses: ok("Product"),
        },
      },
      ...facetsPath,
    },
    components: {
      schemas: {
        ...treeComponents("Region", "regions", false),
        ...treeComponents("Category", "categories", true),
        Product: product,
        ProductRequest: productRequest,
        PatchedProductRequest: { ...productRequest, required: [] },
        PaginatedProductList: paginated("Product"),
        ProductFacets: {
          type: "object",
          properties: {
            taxonomy: { type: "string" },
            rollup: { type: "boolean" },
            results: { type: "array", items: { type: "object" } },
          },
        },
      },
    },
  };
}

async function wait(value: Delay | undefined): Promise<void> {
  if (value === undefined) return;
  await delay(value);
}

function failWith(failure: Failure): Response {
  if (failure === "offline") return HttpResponse.error();
  return HttpResponse.json(
    failure === 403
      ? { detail: "You do not have permission to perform this action." }
      : { detail: "Server error." },
    { status: failure },
  );
}

interface Store {
  rows: TreeRow[];
  ordered: boolean;
  /** Live children by parent, rebuilt after every write (`index = null`). */
  index: Map<number | null, TreeRow[]> | null;
}

function live(store: Store): TreeRow[] {
  return store.rows.filter((row) => row.deleted !== true);
}

function sortSiblings(store: Store, rows: TreeRow[]): TreeRow[] {
  if (!store.ordered) return rows;
  return [...rows].sort((a, b) => (a.position ?? 0) - (b.position ?? 0) || a.id - b.id);
}

function childrenOf(store: Store, parent: number | null): TreeRow[] {
  if (store.index === null) {
    const index = new Map<number | null, TreeRow[]>();
    for (const row of live(store)) {
      const siblings = index.get(row.parent) ?? [];
      siblings.push(row);
      index.set(row.parent, siblings);
    }
    for (const [key, siblings] of index) index.set(key, sortSiblings(store, siblings));
    store.index = index;
  }
  return store.index.get(parent) ?? [];
}

function plain(store: Store, row: TreeRow): Record<string, unknown> {
  const out: Record<string, unknown> = { id: row.id, name: row.name, parent: row.parent };
  if (store.ordered) out.position = row.position ?? 0;
  return out;
}

function node(store: Store, row: TreeRow, children: unknown[] | null): Record<string, unknown> {
  return {
    ...plain(store, row),
    has_children: childrenOf(store, row.id).length > 0,
    children,
  };
}

/** tree/: complete levels up to the node limit, each node saying whether it has children. */
function treeAnswer(store: Store, root: number | null, depth: number, maxNodes: number) {
  const top = childrenOf(store, root);
  if (top.length > maxNodes) {
    return {
      results: top.slice(0, maxNodes).map((row) => node(store, row, null)),
      truncated: true,
    };
  }
  let keptLevels = 1;
  let count = top.length;
  let layer = top;
  let truncated = false;
  while (keptLevels < depth) {
    const below = layer.flatMap((row) => childrenOf(store, row.id));
    if (below.length === 0) break;
    if (count + below.length > maxNodes) {
      truncated = true;
      break;
    }
    count += below.length;
    keptLevels += 1;
    layer = below;
  }
  const build = (row: TreeRow, level: number): Record<string, unknown> => {
    const kids = childrenOf(store, row.id);
    if (level >= keptLevels) return node(store, row, kids.length === 0 ? [] : null);
    return node(
      store,
      row,
      kids.map((kid) => build(kid, level + 1)),
    );
  };
  return { results: top.map((row) => build(row, 1)), truncated };
}

function below(store: Store, id: number): Set<number> {
  const found = new Set<number>();
  const stack = [id];
  while (stack.length > 0) {
    const current = stack.pop() as number;
    for (const row of childrenOf(store, current)) {
      if (!found.has(row.id)) {
        found.add(row.id);
        stack.push(row.id);
      }
    }
  }
  return found;
}

function ancestorsOf(store: Store, row: TreeRow): TreeRow[] {
  const path: TreeRow[] = [];
  const seen = new Set<number>([row.id]);
  let parent = row.parent;
  while (parent !== null && !seen.has(parent)) {
    seen.add(parent);
    const found = live(store).find((candidate) => candidate.id === parent);
    if (found === undefined) break;
    path.unshift(found);
    parent = found.parent;
  }
  return path;
}

/** access/: the granted nodes (each with its path from the root) and every other root. */
function forestAnswer(store: Store, granted: number[], all: boolean) {
  const rows = live(store);
  const roots = sortSiblings(
    store,
    rows.filter((row) => row.parent === null),
  );
  const forestNode = (row: TreeRow, isGranted: boolean, children: unknown[] | null) => ({
    id: row.id,
    label: row.name,
    parent: row.parent,
    granted: isGranted,
    has_children: children === null ? childrenOf(store, row.id).length > 0 : children.length > 0,
    children,
  });
  if (all) {
    return {
      results: roots.map((row) =>
        forestNode(row, true, childrenOf(store, row.id).length > 0 ? null : []),
      ),
      all: true,
      truncated: false,
    };
  }
  const wanted = new Set(granted);
  const tops = rows.filter(
    (row) => wanted.has(row.id) && !ancestorsOf(store, row).some((up) => wanted.has(up.id)),
  );
  const onPath = new Set<number>();
  for (const row of tops) for (const up of ancestorsOf(store, row)) onPath.add(up.id);
  const topIds = new Set(tops.map((row) => row.id));
  const build = (row: TreeRow): Record<string, unknown> => {
    if (topIds.has(row.id)) {
      return forestNode(row, true, childrenOf(store, row.id).length > 0 ? null : []);
    }
    const kids = childrenOf(store, row.id).filter(
      (kid) => onPath.has(kid.id) || topIds.has(kid.id),
    );
    return forestNode(row, false, kids.map(build));
  };
  return {
    results: roots.map((row) =>
      onPath.has(row.id) || topIds.has(row.id) ? build(row) : forestNode(row, false, []),
    ),
    all: false,
    truncated: false,
  };
}

function renumber(store: Store, parent: number | null): void {
  if (!store.ordered) return;
  childrenOf(store, parent).forEach((row, index) => {
    row.position = index;
  });
}

function pageOf<T>(url: URL, rows: T[], pageSize = 50) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const size = Math.min(Number(url.searchParams.get("page_size") ?? pageSize), 100);
  const next = new URL(url.toString());
  next.searchParams.set("page", String(page + 1));
  return {
    count: rows.length,
    next: page * size < rows.length ? next.toString() : null,
    previous: null,
    results: rows.slice((page - 1) * size, page * size),
  };
}

/** Handlers for the schema and the three resources, plus the request log. */
export function treeBackend(options: TreeBackendOptions = {}): TreeBackend {
  const {
    maxNodes = 1000,
    treeFailure,
    lazyFailure,
    ancestorsFailure,
    ancestorsDelay,
    treeDelay,
    lazyDelay,
    search = true,
    granted = {},
    accessAll = false,
    taxonomy = false,
    facetsFailure,
  } = options;
  const regions = options.regions ?? makeRegions();
  const categories = options.categories ?? makeCategories();
  const products = options.products ?? [{ id: 1, name: "Trowel", category: 2, regions: [3] }];
  const stores: Record<string, Store> = {
    regions: { rows: regions, ordered: false, index: null },
    categories: { rows: categories, ordered: true, index: null },
  };
  const requests: URL[] = [];
  const bodies: Array<{ url: URL; body: unknown }> = [];
  const schema = treeOpenApi({ search, taxonomy });

  /** The products the list (and the facets) read: `?regions=`, `?regions_descendants=`, `?search=`. */
  const filteredProducts = (url: URL): ProductRow[] => {
    let rows = products;
    const term = (url.searchParams.get("search") ?? "").trim().toLowerCase();
    if (term !== "") rows = rows.filter((row) => row.name.toLowerCase().includes(term));
    const wanted = url.searchParams
      .getAll("regions")
      .flatMap((value) => value.split(","))
      .filter((value) => value !== "")
      .map(Number);
    if (taxonomy && wanted.length > 0) {
      const store = stores.regions as Store;
      const nodes = new Set(wanted);
      if (url.searchParams.get("regions_descendants") === "true") {
        for (const id of wanted) for (const under of below(store, id)) nodes.add(under);
      }
      rows = rows.filter((row) => row.regions.some((id) => nodes.has(id)));
    }
    return rows;
  };

  /** facets/: rows per region, rolled up to the ancestors with `?rollup=true`. */
  const facetsAnswer = (url: URL) => {
    const store = stores.regions as Store;
    const rollup = url.searchParams.get("rollup") === "true";
    const counted = new Map<number, Set<number>>();
    for (const row of filteredProducts(url)) {
      for (const id of row.regions) {
        const tagged = findRow(store, id);
        if (tagged === undefined) continue;
        const reached = rollup ? [...ancestorsOf(store, tagged), tagged] : [tagged];
        for (const each of reached) {
          const rows = counted.get(each.id) ?? new Set<number>();
          rows.add(row.id);
          counted.set(each.id, rows);
        }
      }
    }
    const order: TreeRow[] = [];
    const visit = (parent: number | null): void => {
      for (const kid of childrenOf(store, parent)) {
        if (counted.has(kid.id)) order.push(kid);
        visit(kid.id);
      }
    };
    visit(null);
    return {
      taxonomy: "regions",
      rollup,
      results: order.map((row) => ({
        id: row.id,
        label: row.name,
        parent: row.parent,
        count: counted.get(row.id)?.size ?? 0,
      })),
    };
  };

  const findRow = (store: Store, id: unknown): TreeRow | undefined =>
    live(store).find((row) => String(row.id) === String(id));
  const missing = (): Response =>
    HttpResponse.json({ detail: "No row matches the given query." }, { status: 404 });

  const treeHandlers = (resource: string): RequestHandler[] => {
    const store = stores[resource] as Store;
    return [
      http.get(`*/api/${resource}/tree/`, async ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const rootParam = url.searchParams.get("root");
        await wait(treeDelay);
        if (rootParam !== null) await wait(lazyDelay);
        if (treeFailure !== undefined) return failWith(treeFailure);
        if (rootParam !== null && lazyFailure !== undefined) return failWith(lazyFailure);
        const depth = Number(url.searchParams.get("depth") ?? "2");
        if (rootParam !== null && findRow(store, rootParam) === undefined) return missing();
        return HttpResponse.json(
          treeAnswer(store, rootParam === null ? null : Number(rootParam), depth, maxNodes),
        );
      }),
      http.get(`*/api/${resource}/access/`, ({ request }) => {
        requests.push(new URL(request.url));
        const ids = granted[resource as "regions" | "categories"] ?? [];
        return HttpResponse.json(forestAnswer(store, ids, accessAll));
      }),
      http.get(`*/api/${resource}/:id/children/`, ({ request, params }) => {
        const url = new URL(request.url);
        requests.push(url);
        const row = findRow(store, params["id"]);
        if (row === undefined) return missing();
        return HttpResponse.json(
          pageOf(
            url,
            childrenOf(store, row.id).map((kid) => node(store, kid, null)),
          ),
        );
      }),
      http.get(`*/api/${resource}/:id/ancestors/`, async ({ request, params }) => {
        requests.push(new URL(request.url));
        await wait(ancestorsDelay);
        if (ancestorsFailure !== undefined) return failWith(ancestorsFailure);
        const row = findRow(store, params["id"]);
        if (row === undefined) return missing();
        return HttpResponse.json(ancestorsOf(store, row).map((above) => node(store, above, null)));
      }),
      http.post(`*/api/${resource}/:id/move/`, async ({ request, params }) => {
        const url = new URL(request.url);
        requests.push(url);
        const body = (await request.json()) as { parent: number | null; position?: number };
        bodies.push({ url, body });
        const row = findRow(store, params["id"]);
        if (row === undefined) return missing();
        if (
          body.parent !== null &&
          (body.parent === row.id || below(store, row.id).has(body.parent))
        ) {
          return HttpResponse.json(
            { parent: ["E340: This node is below the one you move."] },
            { status: 400 },
          );
        }
        const old = row.parent;
        row.parent = body.parent;
        store.index = null;
        if (store.ordered) {
          const siblings = childrenOf(store, body.parent).filter((other) => other.id !== row.id);
          const index = body.position ?? siblings.length;
          siblings.splice(Math.min(index, siblings.length), 0, row);
          siblings.forEach((other, number) => {
            other.position = number;
          });
          store.index = null;
          renumber(store, old);
          store.index = null;
        }
        return HttpResponse.json(node(store, row, null));
      }),
      http.get(`*/api/${resource}/`, ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        let rows = sortSiblings(store, live(store));
        const term = (url.searchParams.get("search") ?? "").trim().toLowerCase();
        if (search && term !== "")
          rows = rows.filter((row) => row.name.toLowerCase().includes(term));
        const parent = url.searchParams.get("parent");
        if (parent !== null) {
          rows = rows.filter((row) =>
            parent === "null" ? row.parent === null : String(row.parent) === parent,
          );
        }
        const under = url.searchParams.get("descendants_of");
        if (under !== null) {
          const ids = below(store, Number(under));
          rows = rows.filter((row) => ids.has(row.id));
        }
        return HttpResponse.json(
          pageOf(
            url,
            rows.map((row) => plain(store, row)),
          ),
        );
      }),
      http.post(`*/api/${resource}/`, async ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const body = (await request.json()) as { name: string; parent?: number | null };
        bodies.push({ url, body });
        const row: TreeRow = {
          id: Math.max(0, ...store.rows.map((other) => other.id)) + 1,
          name: body.name,
          parent: body.parent ?? null,
        };
        if (store.ordered) row.position = childrenOf(store, row.parent).length;
        store.rows.push(row);
        store.index = null;
        return HttpResponse.json(plain(store, row), { status: 201 });
      }),
      http.get(`*/api/${resource}/:id/`, ({ request, params }) => {
        requests.push(new URL(request.url));
        const row = findRow(store, params["id"]);
        return row === undefined ? missing() : HttpResponse.json(plain(store, row));
      }),
      http.patch(`*/api/${resource}/:id/`, async ({ request, params }) => {
        const url = new URL(request.url);
        requests.push(url);
        const body = (await request.json()) as Partial<TreeRow>;
        bodies.push({ url, body });
        const row = findRow(store, params["id"]);
        if (row === undefined) return missing();
        if (body.name !== undefined) row.name = body.name;
        if (body.parent !== undefined) row.parent = body.parent;
        store.index = null;
        return HttpResponse.json(plain(store, row));
      }),
      http.delete(`*/api/${resource}/:id/`, ({ request, params }) => {
        const url = new URL(request.url);
        requests.push(url);
        const row = findRow(store, params["id"]);
        if (row === undefined) return missing();
        const branch = url.searchParams.get("branch") === "true";
        const kids = childrenOf(store, row.id).length;
        if (kids > 0 && !branch) {
          return HttpResponse.json(
            {
              detail: `E341: This node has ${kids} live child node(s). Delete the branch or move them first.`,
              code: "E341",
              field: null,
              conflict: { children: kids },
            },
            { status: 409 },
          );
        }
        for (const id of [row.id, ...below(store, row.id)]) {
          const found = store.rows.find((candidate) => candidate.id === id);
          if (found !== undefined) found.deleted = true;
        }
        store.index = null;
        return new HttpResponse(null, { status: 204 });
      }),
    ];
  };

  const handlers: RequestHandler[] = [
    http.get("*/api/schema/", () => HttpResponse.json(schema)),
    ...treeHandlers("regions"),
    ...treeHandlers("categories"),
    http.get("*/api/products/facets/", async ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      await wait(treeDelay);
      if (facetsFailure !== undefined) return failWith(facetsFailure);
      return taxonomy ? HttpResponse.json(facetsAnswer(url)) : missing();
    }),
    http.get("*/api/products/", ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      return HttpResponse.json(pageOf(url, filteredProducts(url)));
    }),
    http.post("*/api/products/", async ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      const body = (await request.json()) as Omit<ProductRow, "id">;
      bodies.push({ url, body });
      const row: ProductRow = { id: products.length + 1, ...body };
      products.push(row);
      return HttpResponse.json(row, { status: 201 });
    }),
    http.get("*/api/products/:id/", ({ request, params }) => {
      requests.push(new URL(request.url));
      const row = products.find((candidate) => String(candidate.id) === String(params["id"]));
      return row === undefined ? missing() : HttpResponse.json(row);
    }),
    http.patch("*/api/products/:id/", async ({ request, params }) => {
      const url = new URL(request.url);
      requests.push(url);
      const body = (await request.json()) as Partial<ProductRow>;
      bodies.push({ url, body });
      const row = products.find((candidate) => String(candidate.id) === String(params["id"]));
      if (row === undefined) return missing();
      Object.assign(row, body);
      return HttpResponse.json(row);
    }),
  ];

  return {
    handlers,
    requests,
    regions,
    categories,
    products,
    bodies,
    treeRequests: (resource = "regions") =>
      requests.filter((url) => url.pathname.endsWith(`/${resource}/tree/`)),
  };
}
