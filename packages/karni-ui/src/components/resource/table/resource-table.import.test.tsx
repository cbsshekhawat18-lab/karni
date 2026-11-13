/**
 * ResourceTable's Import button (SHARED piece 9): a list whose resource
 * serves `POST /<resource>/import/` offers the CSV import to whoever may
 * create its rows, and opens ResourceImport above the table.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { openApiFixture, server } from "../../../../tests/msw/server";
import { AuthContext, type AuthContextValue } from "../../../auth/provider";
import type { KarniUser } from "../../../auth/types";
import { createKarniClient } from "../../../schema/client";
import { KarniProvider } from "../../../schema/provider";
import { ResourceTable } from "./ResourceTable";

function identity(permissions: string[]): AuthContextValue {
  const user: KarniUser = { id: 1, email: "ada@example.com", roles: ["staff"], permissions };
  return {
    user,
    roles: user.roles,
    status: "authenticated",
    login: () => Promise.resolve({ ok: true, user }),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(),
    adoptTokens: () => Promise.resolve(),
  };
}

/** The fixture with an import operation on events, its create held by `events.event:add`. */
function importableSchema(): Record<string, unknown> {
  const doc = structuredClone(openApiFixture) as unknown as {
    paths: Record<string, Record<string, Record<string, unknown>>>;
  };
  const events = doc.paths["/api/events/"];
  if (events?.["post"] !== undefined)
    events["post"]["x-karni-access"] = { can: ["events.event:add"] };
  doc.paths["/api/events/import/"] = {
    post: { operationId: "events_import_create", responses: {} },
  };
  return doc as unknown as Record<string, unknown>;
}

function mount(permissions: string[]) {
  server.use(http.get("*/api/schema/", () => HttpResponse.json(importableSchema())));
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <AuthContext.Provider value={identity(permissions)}>
      <KarniProvider client={client} queryClient={queryClient}>
        <ResourceTable resource="events" syncUrl={false} onCreate={() => undefined} />
      </KarniProvider>
    </AuthContext.Provider>,
  );
}

describe("ResourceTable import", () => {
  it("offers the import to a role that may create, and opens it above the table", async () => {
    mount(["events.event:add", "events.event:view"]);
    const button = await screen.findByRole("button", { name: "Import" });
    expect(screen.getByRole("button", { name: /New/ })).toBeInTheDocument();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Close the import" })).toBeInTheDocument();
  });

  it("offers neither New nor Import to a role that may only read", async () => {
    mount(["events.event:view"]);
    expect(await screen.findByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New/ })).not.toBeInTheDocument();
  });
});
