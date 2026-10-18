/**
 * Audit fields (BaseModel: id, created_at, updated_at, created_by,
 * updated_by) end to end: the pure helpers, then ResourceTable and
 * ResourceDetail through the real pipeline (createKarniClient → schema fetch
 * → parseOpenApi → component) against
 * - the handwritten msw fixture (tests/msw — audit fields split around the
 *   domain fields), and
 * - the Python side's generated testapp snapshot (tests/fixtures/
 *   schema.testapp.json, D9 — all five audit fields, alphabetical order),
 *   skipped with a pointer when the snapshot is absent.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { server } from "../../../tests/msw/server";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import type { FieldDef } from "../../schema/types";
import { AUDIT_FIELDS, isAuditField, partitionAuditFields } from "./audit-fields";
import { ResourceDetail } from "./detail/ResourceDetail";
import { ResourceTable } from "./table/ResourceTable";

const AUDIT_LABELS = ["Id", "Created at", "Updated at", "Created by", "Updated by"];

function mount(ui: React.ReactElement): void {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

async function headerTexts(): Promise<Array<string | null>> {
  const table = await screen.findByRole("table", undefined, { timeout: 5000 });
  await waitFor(() => expect(within(table).getAllByRole("row").length).toBeGreaterThan(1), {
    timeout: 5000,
  });
  return within(table)
    .getAllByRole("columnheader")
    .map((th) => th.textContent);
}

async function detailLists(): Promise<{ domain: HTMLElement; record: HTMLElement }> {
  const record = await screen.findByRole("region", { name: "Record" }, { timeout: 5000 });
  const domain = record.parentElement?.querySelector("dl");
  if (domain === null || domain === undefined) throw new Error("no domain <dl>");
  return { domain, record };
}

function termsOf(list: Element): Array<string | null> {
  return Array.from(list.querySelectorAll("dt")).map((term) => term.textContent);
}

// pure helpers

function def(name: string, readOnly: boolean): Pick<FieldDef, "name" | "readOnly"> {
  return { name, readOnly };
}

describe("audit-fields helpers", () => {
  it("isAuditField needs an AUDIT_FIELDS name AND readOnly", () => {
    expect(isAuditField(def("created_at", true))).toBe(true);
    expect(isAuditField(def("id", false))).toBe(false); // writable natural key
    expect(isAuditField(def("title", true))).toBe(false);
  });

  it("partitionAuditFields keeps domain order and sorts audit by AUDIT_FIELDS", () => {
    const fields = ["updated_by", "title", "id", "created_at", "capacity", "updated_at"].map(
      (name) => def(name, true),
    );
    const { domain, audit } = partitionAuditFields(fields);
    expect(domain.map((field) => field.name)).toEqual(["title", "capacity"]);
    expect(audit.map((field) => field.name)).toEqual([
      "id",
      "created_at",
      "updated_at",
      "updated_by",
    ]);
    expect(AUDIT_FIELDS).toHaveLength(5);
  });
});

// msw fixture (tests/msw/openapi.ts)

/** Domain columns of the handwritten Event, in declaration order. */
const MSW_DOMAIN_HEADERS = [
  "Title",
  "Description",
  "Starts at",
  "Capacity",
  "Status",
  "Category",
  "Priority",
  "Is public",
  "Organizer",
  "Venue",
  "Tags",
  "Contact email",
  "Website",
];

describe("audit fields against the msw fixture (full stack)", () => {
  it("ResourceTable hides Id/Created at/Updated at; rows still act by id", async () => {
    const onEdit = vi.fn();
    const onRowClick = vi.fn();
    mount(<ResourceTable resource="events" onEdit={onEdit} onRowClick={onRowClick} />);
    // "Actions" is the structural (sr-only) row-actions column.
    expect(await headerTexts()).toEqual([...MSW_DOMAIN_HEADERS, "Actions"]);

    // Default server order is -created_at: "Town Hall" (id 12) leads.
    const user = userEvent.setup();
    const firstRow = within(screen.getByRole("table")).getAllByRole("row")[1];
    expect(firstRow).toHaveTextContent("Town Hall");
    await user.click(within(firstRow).getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 12 }));
    await user.click(within(firstRow).getByText("Town Hall"));
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 12 }));
  });

  it("ResourceTable showAuditFields appends them after the domain columns", async () => {
    mount(<ResourceTable resource="events" showAuditFields />);
    expect(await headerTexts()).toEqual([...MSW_DOMAIN_HEADERS, "Id", "Created at", "Updated at"]);
  });

  it("ResourceTable columns={[{ field: 'created_at' }]} shows just that one", async () => {
    mount(<ResourceTable resource="events" columns={[{ field: "created_at" }]} />);
    expect(await headerTexts()).toEqual([...MSW_DOMAIN_HEADERS, "Created at"]);
  });

  it("ResourceDetail lists domain fields first and audit fields in the Record group", async () => {
    mount(<ResourceDetail resource="events" id={12} />);
    const { domain, record } = await detailLists();
    expect(termsOf(domain)[0]).toBe("Title");
    for (const label of AUDIT_LABELS) expect(termsOf(domain)).not.toContain(label);
    expect(termsOf(record)).toEqual(["Id", "Created at", "Updated at"]);
  });
});

// generated testapp snapshot (D9)

const SNAPSHOT_PATH = join(process.cwd(), "tests", "fixtures", "schema.testapp.json");
const snapshotPresent = existsSync(SNAPSHOT_PATH);

/** The testapp Event's domain columns, in the snapshot's declaration order. */
const SNAPSHOT_DOMAIN_HEADERS = [
  "Capacity",
  "Description",
  "Is public",
  "Organizer",
  "Starts at",
  "Status",
  "Tags",
  "Title",
  "Venue",
];

const snapshotEvents: Array<Record<string, unknown>> = [
  {
    id: "3f6f75d8-f305-48a8-9587-32884b211936",
    created_at: "2026-10-02T11:41:01Z",
    updated_at: "2026-10-02T11:41:01Z",
    created_by: "0c5e0a4e-7b1f-4a43-9c77-3d1b6c0f2a10",
    updated_by: null,
    title: "React workshop",
    description: "",
    starts_at: "2026-11-03T11:30:00Z",
    capacity: null,
    status: "draft",
    is_public: true,
    organizer: null,
    venue: null,
    tags: [],
  },
  {
    id: "39e181ae-05fd-4583-8c86-fb4aa62a9d70",
    created_at: "2026-10-02T11:41:01Z",
    updated_at: "2026-10-02T11:41:01Z",
    created_by: null,
    updated_by: null,
    title: "Django meetup",
    description: "",
    starts_at: "2026-11-02T11:30:00Z",
    capacity: 45,
    status: "published",
    is_public: false,
    organizer: null,
    venue: null,
    tags: [],
  },
];

function serveSnapshotBackend(): void {
  const openApi = JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8")) as Record<string, unknown>;
  server.use(
    http.get("*/api/schema/", () => HttpResponse.json(openApi)),
    http.get("*/api/events/", () =>
      HttpResponse.json({
        count: snapshotEvents.length,
        next: null,
        previous: null,
        results: snapshotEvents,
      }),
    ),
    http.get("*/api/events/:id/", ({ params }) => {
      const found = snapshotEvents.find((event) => event["id"] === params["id"]);
      return found === undefined
        ? HttpResponse.json({ detail: "Not found." }, { status: 404 })
        : HttpResponse.json(found);
    }),
  );
}

describe.skipIf(!snapshotPresent)(
  "audit fields against the generated testapp snapshot (D9; schema.testapp.json absent? " +
    "see tests/fixtures/README.md)",
  () => {
    it("ResourceTable leads with domain fields; no audit column or filter", async () => {
      serveSnapshotBackend();
      const onEdit = vi.fn();
      mount(<ResourceTable resource="events" onEdit={onEdit} />);
      expect(await headerTexts()).toEqual([...SNAPSHOT_DOMAIN_HEADERS, "Actions"]);
      // created_by/updated_by are declared relation filter params in the
      // snapshot — they must not take filter-bar slots either.
      for (const label of AUDIT_LABELS) expect(screen.queryByText(label)).not.toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(screen.getAllByRole("button", { name: "Edit" })[1]);
      expect(onEdit).toHaveBeenCalledWith(
        expect.objectContaining({ id: "39e181ae-05fd-4583-8c86-fb4aa62a9d70" }),
      );
    });

    it("showAuditFields appends all five in AUDIT_FIELDS order (schema is alphabetical)", async () => {
      serveSnapshotBackend();
      mount(<ResourceTable resource="events" showAuditFields />);
      expect(await headerTexts()).toEqual([...SNAPSHOT_DOMAIN_HEADERS, ...AUDIT_LABELS]);
    });

    it("ResourceDetail ends with the muted Record group", async () => {
      serveSnapshotBackend();
      mount(<ResourceDetail resource="events" id="3f6f75d8-f305-48a8-9587-32884b211936" />);
      const { domain, record } = await detailLists();
      expect(termsOf(domain)).toEqual(SNAPSHOT_DOMAIN_HEADERS);
      expect(termsOf(record)).toEqual(AUDIT_LABELS);
      expect(within(domain).getByText("React workshop").closest("dd")).toHaveClass(
        "text-foreground",
      );
      expect(
        within(record).getByText("3f6f75d8-f305-48a8-9587-32884b211936").closest("dd"),
      ).toHaveClass("text-muted-foreground");
    });
  },
);
