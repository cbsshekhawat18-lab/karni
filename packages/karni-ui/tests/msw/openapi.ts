/**
 * Handwritten OpenAPI 3.0.3 fixture simulating a Karni backend
 * (drf-spectacular with COMPONENT_SPLIT_REQUEST=True — api contract B14).
 *
 * It exercises every construct the schema parser must handle (D1):
 * - split request/response components (Event vs EventRequest/PatchedEventRequest),
 * - enums via `allOf: [$ref]` + siblings (status) and via
 *   `oneOf: [XEnum, NullEnum]` (category) / `oneOf: [XEnum, BlankEnum]` (priority),
 * - `required` arrays on BOTH components (the parser must use the create
 *   request's array ONLY),
 * - request-side `format: binary` vs response-side `format: uri` (poster),
 * - a request-only writeOnly field (internal_note),
 * - x-karni-relation single (organizer, venue) and many (tags),
 * - a JSONField "any" schema (metadata),
 * - read-only resources without a create operation (venues, tags, users),
 * - x-karni-resource on list ops and x-karni-auth-mode at the root,
 * - list query params (page/page_size/ordering/search/expand enum/filters).
 */

const nullEnum = { enum: [null] };
const blankEnum = { enum: [""] };

const statusEnum = {
  enum: ["draft", "published"],
  type: "string",
  description: "* `draft` - Draft\n* `published` - Published",
};

const categoryEnum = {
  enum: ["conference", "meetup", "workshop"],
  type: "string",
  description: "* `conference` - Conference\n* `meetup` - Meetup\n* `workshop` - Workshop",
};

const priorityEnum = {
  enum: ["low", "high"],
  type: "string",
  description: "* `low` - Low\n* `high` - High",
};

const eventRelations = {
  organizer: { "x-karni-relation": { resource: "users", many: false } },
  venue: { "x-karni-relation": { resource: "venues", many: false } },
  tags: { "x-karni-relation": { resource: "tags", many: true } },
};

/** Response component (COMPONENT_SPLIT_REQUEST read side). */
const eventComponent = {
  type: "object",
  // Deliberately includes read-only members: the parser must IGNORE this
  // array and take `required` from the create request component only (D1).
  required: ["id", "title", "starts_at", "status", "created_at", "updated_at"],
  properties: {
    id: { type: "integer", readOnly: true },
    title: { type: "string", maxLength: 200 },
    description: { type: "string" },
    starts_at: { type: "string", format: "date-time" },
    capacity: { type: "integer", nullable: true, minimum: 0, maximum: 10000 },
    status: { allOf: [{ $ref: "#/components/schemas/StatusEnum" }], readOnly: true },
    category: {
      oneOf: [
        { $ref: "#/components/schemas/CategoryEnum" },
        { $ref: "#/components/schemas/NullEnum" },
      ],
      nullable: true,
    },
    priority: {
      oneOf: [
        { $ref: "#/components/schemas/PriorityEnum" },
        { $ref: "#/components/schemas/BlankEnum" },
      ],
    },
    is_public: { type: "boolean" },
    organizer: { type: "integer", nullable: true, ...eventRelations.organizer },
    venue: { type: "integer", nullable: true, ...eventRelations.venue },
    tags: { type: "array", items: { type: "integer" }, ...eventRelations.tags },
    poster: { type: "string", format: "uri", nullable: true },
    contact_email: { type: "string", format: "email", maxLength: 254 },
    website: { type: "string", format: "uri", maxLength: 200 },
    metadata: {},
    created_at: { type: "string", format: "date-time", readOnly: true },
    updated_at: { type: "string", format: "date-time", readOnly: true },
  },
};

/** Create request component (write side; readOnly fields are absent). */
const eventRequestComponent = {
  type: "object",
  required: ["title", "starts_at"],
  properties: {
    title: { type: "string", minLength: 1, maxLength: 200 },
    description: { type: "string" },
    starts_at: { type: "string", format: "date-time" },
    capacity: { type: "integer", nullable: true, minimum: 0, maximum: 10000 },
    category: {
      oneOf: [
        { $ref: "#/components/schemas/CategoryEnum" },
        { $ref: "#/components/schemas/NullEnum" },
      ],
      nullable: true,
    },
    priority: {
      oneOf: [
        { $ref: "#/components/schemas/PriorityEnum" },
        { $ref: "#/components/schemas/BlankEnum" },
      ],
    },
    is_public: { type: "boolean" },
    organizer: { type: "integer", nullable: true, ...eventRelations.organizer },
    venue: { type: "integer", nullable: true, ...eventRelations.venue },
    tags: { type: "array", items: { type: "integer" }, ...eventRelations.tags },
    poster: { type: "string", format: "binary", nullable: true },
    contact_email: { type: "string", format: "email", maxLength: 254 },
    website: { type: "string", format: "uri", maxLength: 200 },
    metadata: {},
    internal_note: { type: "string", writeOnly: true, maxLength: 500 },
  },
};

const patchedEventRequestComponent = {
  ...eventRequestComponent,
  required: undefined,
};

function paginatedComponent(itemRef: string) {
  return {
    type: "object",
    required: ["count", "results"],
    properties: {
      count: { type: "integer", example: 123 },
      next: { type: "string", format: "uri", nullable: true },
      previous: { type: "string", format: "uri", nullable: true },
      results: { type: "array", items: { $ref: itemRef } },
    },
  };
}

const venueComponent = {
  type: "object",
  required: ["id", "name", "city"],
  properties: {
    id: { type: "integer", readOnly: true },
    name: { type: "string", maxLength: 200 },
    city: { type: "string", maxLength: 100 },
  },
};

const tagComponent = {
  type: "object",
  required: ["id", "name"],
  properties: {
    id: { type: "integer", readOnly: true },
    name: { type: "string", maxLength: 100 },
  },
};

const userComponent = {
  type: "object",
  required: ["id", "email"],
  properties: {
    id: { type: "integer", readOnly: true },
    email: { type: "string", format: "email", maxLength: 254 },
    first_name: { type: "string", maxLength: 150 },
    last_name: { type: "string", maxLength: 150 },
  },
};

function queryParam(name: string, schema: Record<string, unknown>) {
  return { in: "query", name, required: false, schema };
}

const pathIdParam = {
  in: "path",
  name: "id",
  required: true,
  schema: { type: "integer" },
};

const expandParam = {
  in: "query",
  name: "expand",
  required: false,
  schema: {
    type: "array",
    items: { type: "string", enum: ["organizer", "venue", "tags"] },
  },
  explode: true,
  style: "form",
};

function jsonResponse(ref: string, status = "200") {
  return {
    [status]: {
      content: { "application/json": { schema: { $ref: ref } } },
      description: "",
    },
  };
}

function listPaths(resource: string, componentName: string, extraListParams: unknown[] = []) {
  return {
    [`/api/${resource}/`]: {
      get: {
        operationId: `${resource}_list`,
        "x-karni-resource": resource,
        parameters: [
          queryParam("ordering", { type: "string" }),
          queryParam("page", { type: "integer" }),
          queryParam("page_size", { type: "integer" }),
          queryParam("search", { type: "string" }),
          ...extraListParams,
        ],
        responses: jsonResponse(`#/components/schemas/Paginated${componentName}List`),
      },
    },
    [`/api/${resource}/{id}/`]: {
      get: {
        operationId: `${resource}_retrieve`,
        parameters: [pathIdParam],
        responses: jsonResponse(`#/components/schemas/${componentName}`),
      },
    },
  };
}

export const openApiFixture = {
  openapi: "3.0.3",
  info: { title: "Karni Test API", version: "1.0.0" },
  "x-karni-auth-mode": "jwt",
  paths: {
    "/api/events/": {
      get: {
        operationId: "events_list",
        "x-karni-resource": "events",
        parameters: [
          queryParam("category", { type: "string", enum: ["conference", "meetup", "workshop"] }),
          expandParam,
          queryParam("is_public", { type: "boolean" }),
          queryParam("ordering", { type: "string" }),
          queryParam("organizer", { type: "integer" }),
          queryParam("page", { type: "integer" }),
          queryParam("page_size", { type: "integer" }),
          queryParam("search", { type: "string" }),
          queryParam("status", { type: "string", enum: ["draft", "published"] }),
          queryParam("venue", { type: "integer" }),
        ],
        responses: jsonResponse("#/components/schemas/PaginatedEventList"),
      },
      post: {
        operationId: "events_create",
        requestBody: {
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/EventRequest" } },
            "multipart/form-data": { schema: { $ref: "#/components/schemas/EventRequest" } },
          },
          required: true,
        },
        responses: jsonResponse("#/components/schemas/Event", "201"),
      },
    },
    "/api/events/{id}/": {
      get: {
        operationId: "events_retrieve",
        parameters: [pathIdParam, expandParam],
        responses: jsonResponse("#/components/schemas/Event"),
      },
      put: {
        operationId: "events_update",
        parameters: [pathIdParam],
        requestBody: {
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/EventRequest" } },
            "multipart/form-data": { schema: { $ref: "#/components/schemas/EventRequest" } },
          },
          required: true,
        },
        responses: jsonResponse("#/components/schemas/Event"),
      },
      patch: {
        operationId: "events_partial_update",
        parameters: [pathIdParam],
        requestBody: {
          content: {
            "application/json": { schema: { $ref: "#/components/schemas/PatchedEventRequest" } },
            "multipart/form-data": {
              schema: { $ref: "#/components/schemas/PatchedEventRequest" },
            },
          },
        },
        responses: jsonResponse("#/components/schemas/Event"),
      },
      delete: {
        operationId: "events_destroy",
        parameters: [pathIdParam],
        responses: { "204": { description: "No response body" } },
      },
    },
    ...listPaths("venues", "Venue"),
    ...listPaths("tags", "Tag"),
    ...listPaths("users", "User"),
  },
  components: {
    schemas: {
      BlankEnum: blankEnum,
      CategoryEnum: categoryEnum,
      Event: eventComponent,
      EventRequest: eventRequestComponent,
      NullEnum: nullEnum,
      PaginatedEventList: paginatedComponent("#/components/schemas/Event"),
      PaginatedTagList: paginatedComponent("#/components/schemas/Tag"),
      PaginatedUserList: paginatedComponent("#/components/schemas/User"),
      PaginatedVenueList: paginatedComponent("#/components/schemas/Venue"),
      PatchedEventRequest: patchedEventRequestComponent,
      PriorityEnum: priorityEnum,
      StatusEnum: statusEnum,
      Tag: tagComponent,
      User: userComponent,
      Venue: venueComponent,
    },
  },
};

/** The same document with a different root auth mode (session-mode suites). */
export function openApiFixtureWithAuthMode(mode: "jwt" | "session"): typeof openApiFixture {
  return { ...openApiFixture, "x-karni-auth-mode": mode };
}
