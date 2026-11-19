/**
 * The family screens against the msw backend: the layout's two frames and
 * named menus, the home per audience, the timeline (paging, kinds, the
 * change history beside it), the inbox (bell, page, marks, choices), the
 * people list and the person page (facts, tabs, merge and erase behind their
 * grants), search part by part with the keyboard, and sign-up. Each screen
 * also passes axe.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axeViolations } from "../../../tests/axe";
import { openApiFixture } from "../../../tests/msw/openapi";
import { server } from "../../../tests/msw/server";
import { AuthContext, type AuthContextValue } from "../../auth/provider";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { ThemeProvider } from "../../theme/theme";
import { Toaster } from "../toast/toaster";
import { accountSections, unregisterAccountSection } from "../account/sections";
import { SignUpForm } from "../account/SignUpForm";
import { audienceOf } from "./audience";
import { FamilyHome } from "./family-home";
import { FamilyLayout } from "./family-layout";
import { EmailChoices, InboxBell, InboxPage } from "./inbox";
import { PeoplePage, PersonPage } from "./people";
import { registerFamily } from "./register";
import {
  registerPersonTab,
  registerPublicHome,
  registerTimelineKind,
  timelineKindLabel,
  unregisterPersonTab,
  unregisterPublicHome,
  unregisterTimelineKind,
} from "./registry";
import { registerRecordLink, unregisterRecordLink } from "../resource/record-links";
import { SearchPage, searchHitHref } from "./search";
import { Timeline } from "./timeline";

const API = "http://localhost/api";

function auth(roles: string[] | null, over: Partial<AuthContextValue> = {}): AuthContextValue {
  const signedIn = roles !== null;
  return {
    user: signedIn ? { id: 7, email: "ines@example.com", roles } : null,
    roles: roles ?? [],
    status: signedIn ? "authenticated" : "anonymous",
    login: () =>
      Promise.resolve({ ok: true, user: { id: 7, email: "ines@example.com", roles: [] } }),
    logout: vi.fn(() => Promise.resolve()),
    refresh: vi.fn(() => Promise.resolve()),
    adoptTokens: vi.fn(() => Promise.resolve()),
    ...over,
  };
}

function mount(ui: ReactNode, roles: string[] | null = ["shop-staff"], over = {}) {
  const client = createKarniClient({ baseUrl: API });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const value = auth(roles, over);
  const view = render(
    <ThemeProvider>
      <KarniProvider client={client} queryClient={queryClient}>
        <AuthContext.Provider value={value}>
          {ui}
          <Toaster />
        </AuthContext.Provider>
      </KarniProvider>
    </ThemeProvider>,
  );
  return { ...view, auth: value };
}

function menus(byName: Record<string, Array<{ label: string; route: string }>>): void {
  server.use(
    http.get(`${API}/navigation/`, ({ request }) => {
      const menu = new URL(request.url).searchParams.get("menu") ?? "app";
      const items = (byName[menu] ?? []).map((item) => ({ ...item, icon: null, children: [] }));
      return HttpResponse.json({ items });
    }),
    http.get(`${API}/preferences/public/`, () =>
      HttpResponse.json({ name: "Harbour Goods", address: "4 Quay Road", phone: "", email: "" }),
    ),
    http.get(`${API}/inbox/unread/`, () => HttpResponse.json({ count: 3 })),
    http.get(`${API}/dashboard/`, () => HttpResponse.json({ tiles: [] })),
  );
}

afterEach(() => {
  unregisterPublicHome("shop");
  unregisterPersonTab("orders");
  unregisterTimelineKind("commerce.order.paid");
  unregisterAccountSection("addresses");
  unregisterAccountSection("messages");
});

describe("who is looking", () => {
  it("keeps the family's customer role a customer, and any other role staff", () => {
    expect(audienceOf("loading", [])).toBe("loading");
    expect(audienceOf("anonymous", [])).toBe("visitor");
    expect(audienceOf("authenticated", ["customer"])).toBe("customer");
    expect(audienceOf("authenticated", ["customer", "crm-rep"])).toBe("staff");
    expect(audienceOf("authenticated", ["member"], ["member"])).toBe("customer");
  });
});

describe("FamilyLayout", () => {
  it("shows a storefront page in the site's frame with the public and account menus", async () => {
    menus({
      public: [{ label: "Products", route: "/shop/catalogue" }],
      account: [{ label: "Your orders", route: "/orders" }],
    });
    const navigate = vi.fn();
    const { container } = mount(
      <FamilyLayout pathname="/shop/catalogue" navigate={navigate} area="store" isPublic inbox>
        <h1>Catalogue</h1>
      </FamilyLayout>,
      ["customer"],
    );
    const site = await screen.findByRole("navigation", { name: "Site" });
    expect(within(site).getByRole("link", { name: "Products" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("link", { name: "Your orders" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Inbox, 3 unread" })).toBeInTheDocument();
    expect(await screen.findByText("Harbour Goods", { selector: "footer span" })).toBeVisible();
    await userEvent.click(screen.getByRole("link", { name: "Your orders" }));
    expect(navigate).toHaveBeenCalledWith("/orders");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the home in the back office to staff and in the storefront to customers", async () => {
    menus({ app: [{ label: "Orders", route: "/orders" }] });
    registerPublicHome({ key: "shop", component: () => <p>Front page</p>, path: "/shop" });
    const staff = mount(
      <FamilyLayout pathname="/" navigate={vi.fn()} inbox>
        <p>Tiles</p>
      </FamilyLayout>,
    );
    expect(await screen.findByRole("link", { name: "Orders" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Storefront" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Site" })).not.toBeInTheDocument();
    staff.unmount();
    mount(
      <FamilyLayout pathname="/" navigate={vi.fn()}>
        <p>Front</p>
      </FamilyLayout>,
      ["customer"],
    );
    expect(await screen.findByRole("link", { name: "Sign out" }).catch(() => null)).toBeNull();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Orders" })).not.toBeInTheDocument();
  });

  it("asks a visitor to sign in on a back-office page", async () => {
    menus({});
    mount(
      <FamilyLayout pathname="/people" navigate={vi.fn()}>
        <p>Secret</p>
      </FamilyLayout>,
      null,
    );
    expect(screen.queryByText("Secret")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });
});

describe("FamilyHome", () => {
  it("says what to install when the project holds no part", async () => {
    menus({});
    const { container } = mount(<FamilyHome navigate={vi.fn()} parts={[]} />);
    expect(await screen.findByText("Nothing is installed yet")).toBeInTheDocument();
    expect(screen.getByText("karni recipes add shop")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("gives staff their tiles and everyone else the public home", async () => {
    menus({});
    server.use(
      http.get(`${API}/dashboard/`, () =>
        HttpResponse.json({
          tiles: [
            {
              key: "shop.revenue",
              title: "Revenue",
              kind: "stat",
              size: "full",
              order: 1,
              description: "",
              link: null,
              resource: null,
              filters: {},
              columns: [],
              limit: 5,
              data: {
                values: [{ label: "Today", value: "12.00", format: "money", link: null }],
                currency: "EUR",
              },
            },
          ],
        }),
      ),
    );
    registerPublicHome({ key: "shop", component: () => <p>Front page</p> });
    const staff = mount(<FamilyHome navigate={vi.fn()} parts={["shop"]} />);
    expect(await screen.findByText("Revenue")).toBeInTheDocument();
    staff.unmount();
    mount(<FamilyHome navigate={vi.fn()} parts={["shop"]} />, null);
    expect(screen.getByText("Front page")).toBeInTheDocument();
  });

  it("tells staff where tiles come from when their role has none", async () => {
    menus({});
    mount(<FamilyHome navigate={vi.fn()} parts={["crm"]} />);
    expect(await screen.findByText("No tiles for your roles yet")).toBeInTheDocument();
  });
});

const ENTRY = {
  occurred_at: "2026-11-13T09:12:00+00:00",
  body: "",
  source: "commerce",
  actor: null,
  actor_name: "",
  person: "p1",
  event: null,
  links: [{ model: "karni_commerce.order", id: "o1", resource: "orders" }],
  data: {},
};

describe("Timeline", () => {
  it("pages with the cursor, filters by kind and shows the changes beside it", async () => {
    const asked: URLSearchParams[] = [];
    server.use(
      http.get(`${API}/timeline/`, ({ request }) => {
        const query = new URL(request.url).searchParams;
        asked.push(query);
        if (query.get("cursor") === "next1") {
          return HttpResponse.json({
            results: [
              { ...ENTRY, id: "e3", kind: "people.person.linked", title: "Account linked" },
            ],
            next: null,
          });
        }
        return HttpResponse.json({
          results: [
            { ...ENTRY, id: "e1", kind: "commerce.order.paid", title: "Order 1001 paid" },
            {
              ...ENTRY,
              id: "e2",
              kind: "crm.call",
              title: "Called about the renewal",
              body: "Wants blue.",
            },
          ].filter((entry) => !query.get("kind") || entry.kind === query.get("kind")),
          next: query.get("kind") ? null : "next1",
        });
      }),
      http.get(`${API}/people/p1/history/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    registerTimelineKind("commerce.order.paid", { label: "Order paid" });
    const navigate = vi.fn();
    const { container } = mount(
      <Timeline
        person="p1"
        history={{ resource: "people", id: "p1" }}
        navigate={navigate}
        hrefFor={(resource, id) => `/${resource}/${id}`}
      />,
    );
    expect(await screen.findByText("Order 1001 paid")).toBeInTheDocument();
    expect(screen.getByText("Wants blue.")).toBeInTheDocument();
    expect(asked[0]?.get("person")).toBe("p1");
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByText("Account linked")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Show"), "Order paid");
    await waitFor(() => expect(screen.queryByText("Called about the renewal")).toBeNull());
    expect(asked.at(-1)?.get("kind")).toBe("commerce.order.paid");
    await userEvent.click(screen.getAllByRole("link", { name: "Open order" })[0] as HTMLElement);
    expect(navigate).toHaveBeenCalledWith("/orders/o1");
    expect(screen.getByRole("tab", { name: "Changes" })).toBeInTheDocument();
    expect(timelineKindLabel("bookings.booking.cancelled")).toBe("Booking cancelled");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("links an entry's first record with the entry's data (an order by its number)", async () => {
    server.use(
      http.get(`${API}/timeline/`, () =>
        HttpResponse.json({
          results: [
            {
              ...ENTRY,
              id: "e9",
              kind: "commerce.order.paid",
              title: "Order 1001 paid",
              data: { number: 1001 },
            },
          ],
          next: null,
        }),
      ),
    );
    registerRecordLink("orders", (row) =>
      row["number"] ? `/orders/${String(row["number"])}` : null,
    );
    mount(<Timeline person="p1" />);
    expect(await screen.findByRole("link", { name: "Open order" })).toHaveAttribute(
      "href",
      "/orders/1001",
    );
    unregisterRecordLink("orders");
  });

  it("hides the changes tab from who may not read the history", async () => {
    server.use(
      http.get(`${API}/timeline/`, () => HttpResponse.json({ results: [], next: null })),
      http.get(`${API}/people/p1/history/`, () =>
        HttpResponse.json({ detail: "no" }, { status: 403 }),
      ),
    );
    mount(<Timeline person="p1" history={{ resource: "people", id: "p1" }} />);
    expect(await screen.findByText("Nothing on the timeline yet")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("tab", { name: "Changes" })).toBeNull());
  });
});

const NOTE = {
  kind: "commerce.order_paid",
  body: "Thank you.",
  read_at: null,
  created_at: "2026-11-13T09:12:00+00:00",
};

describe("the inbox", () => {
  it("lists, filters, marks one read and marks all read", async () => {
    const posted: string[] = [];
    let unreadOnly = false;
    server.use(
      http.get(`${API}/inbox/`, ({ request }) => {
        unreadOnly = new URL(request.url).searchParams.get("unread") === "true";
        const results = [
          { ...NOTE, id: 1, title: "Order 1001 is paid", link: "/orders/1001", read: false },
          { ...NOTE, id: 2, title: "Order 1000 is paid", link: "", read: true },
        ].filter((row) => !unreadOnly || !row.read);
        return HttpResponse.json({ count: results.length, unread: 1, next: null, results });
      }),
      http.post(`${API}/inbox/:id/read/`, ({ params }) => {
        posted.push(`read ${String(params["id"])}`);
        return HttpResponse.json({});
      }),
      http.post(`${API}/inbox/read-all/`, () => {
        posted.push("all");
        return HttpResponse.json({ updated: 1 });
      }),
    );
    const navigate = vi.fn();
    const { container } = mount(<InboxPage navigate={navigate} />, ["customer"]);
    expect(await screen.findByText("Order 1001 is paid")).toBeInTheDocument();
    expect(screen.getByText("1 unread")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: /Order 1001 is paid/ }));
    expect(navigate).toHaveBeenCalledWith("/orders/1001");
    await waitFor(() => expect(posted).toContain("read 1"));
    await userEvent.click(screen.getByRole("switch", { name: "Unread only" }));
    await waitFor(() => expect(screen.queryByText("Order 1000 is paid")).toBeNull());
    expect(unreadOnly).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(posted).toContain("all"));
    expect(await axeViolations(container)).toEqual([]);
  });

  it("puts the unread count on the bell, and hides it when the inbox is off", async () => {
    server.use(http.get(`${API}/inbox/unread/`, () => HttpResponse.json({ count: 2 })));
    const on = mount(<InboxBell />, ["customer"]);
    expect(await screen.findByRole("link", { name: "Inbox, 2 unread" })).toHaveAttribute(
      "href",
      "/inbox",
    );
    on.unmount();
    server.use(http.get(`${API}/inbox/unread/`, () => HttpResponse.json({}, { status: 404 })));
    mount(<InboxBell />, ["customer"]);
    await waitFor(() => expect(screen.queryByRole("link", { name: /Inbox/ })).toBeNull());
  });

  it("switches one kind off by email for the person", async () => {
    const patched: unknown[] = [];
    server.use(
      http.get(`${API}/inbox/choices/`, () =>
        HttpResponse.json([
          {
            kind: "commerce.order_paid",
            title: "Order paid",
            describe: "The receipt.",
            audience: "the buyer",
            marketing: false,
            channels: ["email", "inbox"],
            email: true,
            inbox: true,
          },
        ]),
      ),
      http.patch(`${API}/inbox/choices/commerce.order_paid/`, async ({ request }) => {
        patched.push(await request.json());
        return HttpResponse.json({});
      }),
    );
    const { container } = mount(<EmailChoices />, ["customer"]);
    await userEvent.click(await screen.findByRole("switch", { name: "Email: Order paid" }));
    await waitFor(() => expect(patched).toEqual([{ email: false }]));
    expect(await axeViolations(container)).toEqual([]);
  });

  it("registers the account sections of the contracts the project holds", () => {
    registerFamily({ people: true, notify: true });
    expect(accountSections().map((section) => section.key)).toEqual(["addresses", "messages"]);
  });
});

const PEOPLE_SCHEMA = {
  ...openApiFixture,
  paths: {
    ...openApiFixture.paths,
    "/api/people/": {
      get: {
        operationId: "people_list",
        "x-karni-resource": "people",
        parameters: ["ordering", "page", "page_size", "search", "facts", "orders__gte"].map(
          (name) => ({ in: "query", name, required: false, schema: { type: "string" } }),
        ),
        responses: {
          "200": {
            description: "",
            content: {
              "application/json": { schema: { $ref: "#/components/schemas/PaginatedPersonList" } },
            },
          },
        },
      },
    },
  },
  components: {
    schemas: {
      ...openApiFixture.components.schemas,
      Person: {
        type: "object",
        properties: {
          id: { type: "string", format: "uuid", readOnly: true },
          display_name: { type: "string" },
          email: { type: "string", format: "email" },
          phone: { type: "string" },
        },
      },
      PaginatedPersonList: {
        type: "object",
        properties: {
          count: { type: "integer" },
          next: { type: "string", nullable: true },
          previous: { type: "string", nullable: true },
          results: { type: "array", items: { $ref: "#/components/schemas/Person" } },
        },
      },
    },
  },
};

const FACTS = [
  { name: "orders", label: "Orders", kind: "count", source: "karni_commerce", description: "" },
  {
    name: "total_spent",
    label: "Total spent",
    kind: "money",
    source: "karni_commerce",
    description: "",
  },
];

describe("people", () => {
  it("lists people with the facts of every part, a pinned filter and a link to each", async () => {
    const asked: URLSearchParams[] = [];
    server.use(
      http.get(`${API}/schema/`, () => HttpResponse.json(PEOPLE_SCHEMA)),
      http.get(`${API}/people/facts/`, () => HttpResponse.json(FACTS)),
      http.get(`${API}/preferences/public/`, () =>
        HttpResponse.json({ name: "Shop", currency: "EUR" }),
      ),
      http.get(`${API}/people/`, ({ request }) => {
        asked.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: "p1",
              display_name: "Ines Moreau",
              email: "ines@example.com",
              phone: "",
              facts: { orders: 3, total_spent: "120.00" },
            },
          ],
        });
      }),
    );
    const navigate = vi.fn();
    mount(<PeoplePage label="Customers" filters={{ orders__gte: "1" }} navigate={navigate} />);
    expect(await screen.findByRole("heading", { name: "Customers", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("Ines Moreau")).toBeInTheDocument();
    expect(screen.getByText("€120.00")).toBeInTheDocument();
    expect(asked.at(-1)?.get("facts")).toBe("orders,total_spent");
    expect(asked.at(-1)?.get("orders__gte")).toBe("1");
  });

  function person(can: { merge: boolean; erase: boolean }) {
    server.use(
      http.get(`${API}/people/facts/`, () => HttpResponse.json(FACTS)),
      http.get(`${API}/preferences/public/`, () =>
        HttpResponse.json({ name: "Shop", currency: "EUR" }),
      ),
      http.get(`${API}/people/p1/`, () =>
        HttpResponse.json({
          id: "p1",
          display_name: "Ines Moreau",
          email: "ines@example.com",
          phone: "+33 4 00 00 00 00",
          facts: { orders: 3, total_spent: "120.00" },
          can,
        }),
      ),
      http.get(`${API}/timeline/`, () => HttpResponse.json({ results: [], next: null })),
      http.get(`${API}/people/p1/history/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get(`${API}/people-addresses/`, () =>
        HttpResponse.json({
          count: 1,
          results: [
            {
              id: "a1",
              label: "Home",
              line1: "4 Rue des Lilas",
              city: "Lyon",
              country: "FR",
              is_default_shipping: true,
            },
          ],
        }),
      ),
      http.get(`${API}/people-memberships/`, () =>
        HttpResponse.json({
          count: 1,
          results: [{ id: "m1", organisation: { id: "o1", name: "Atelier Nord" }, title: "Buyer" }],
        }),
      ),
    );
  }

  it("shows one person's facts, details, a part's tab and the timeline", async () => {
    person({ merge: false, erase: false });
    registerPersonTab({
      key: "orders",
      title: "Orders",
      component: ({ personId }) => <p>Orders of {personId}</p>,
    });
    const { container } = mount(<PersonPage id="p1" navigate={vi.fn()} listLabel="Customers" />);
    expect(
      await screen.findByRole("heading", { name: "Ines Moreau", level: 1 }),
    ).toBeInTheDocument();
    expect(await screen.findByText("€120.00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merge" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Erase" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Details" }));
    expect(await screen.findByText(/4 Rue des Lilas, Lyon, FR/)).toBeInTheDocument();
    expect(await screen.findByText("Atelier Nord")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Orders" }));
    expect(screen.getByText("Orders of p1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to customers" })).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("merges a duplicate after the plan, and erases behind the explicit grants", async () => {
    person({ merge: true, erase: true });
    const merged: unknown[] = [];
    let erased = false;
    server.use(
      http.get(`${API}/people/`, () =>
        HttpResponse.json({
          count: 2,
          next: null,
          previous: null,
          results: [
            { id: "p1", display_name: "Ines Moreau", email: "ines@example.com" },
            { id: "p2", display_name: "Ines M.", email: "ines+shop@example.com" },
          ],
        }),
      ),
      http.get(`${API}/people/p1/merge-plan/`, () =>
        HttpResponse.json({
          keep: "p1",
          drop: "p2",
          allowed: true,
          moves: [{ model: "karni_commerce.Order", field: "person", kind: "foreign_key", rows: 2 }],
          refusals: [],
          fills: { phone: "+33" },
        }),
      ),
      http.post(`${API}/people/p1/merge/`, async ({ request }) => {
        merged.push(await request.json());
        return HttpResponse.json({});
      }),
      http.post(`${API}/people/p1/erase/`, () => {
        erased = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const navigate = vi.fn();
    mount(<PersonPage id="p1" navigate={navigate} />, ["admin"]);
    await userEvent.click(await screen.findByRole("button", { name: "Merge" }));
    await userEvent.type(screen.getByLabelText("Find the other record"), "ines");
    await userEvent.click(await screen.findByRole("button", { name: /Ines M\./ }));
    expect(await screen.findByText("2 Order rows move here")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(merged).toEqual([{ drop: "p2" }]));
    await userEvent.click(screen.getByRole("button", { name: "Erase" }));
    await userEvent.click(await screen.findByRole("button", { name: "Erase the data" }));
    await waitFor(() => expect(erased).toBe(true));
    expect(navigate).toHaveBeenCalledWith("/people");
  });
});

describe("SearchPage", () => {
  it("shows the results part by part and walks them with the keyboard", async () => {
    server.use(
      http.get(`${API}/search/`, () =>
        HttpResponse.json({
          query: "ines",
          groups: [
            {
              resource: "people",
              label: "People",
              part: "people",
              part_label: "People",
              hits: [
                {
                  resource: "people",
                  id: "p1",
                  title: "Ines Moreau",
                  subtitle: "ines@example.com",
                  score: 1,
                },
              ],
            },
            {
              resource: "orders",
              label: "Orders",
              part: "karni_commerce",
              part_label: "Commerce",
              hits: [{ resource: "orders", id: "o1", title: "1001", subtitle: null, score: 0.5 }],
            },
          ],
        }),
      ),
    );
    const onQueryChange = vi.fn();
    const { container } = mount(
      <SearchPage
        query="ines"
        onQueryChange={onQueryChange}
        routes={["/people/$id", "/orders/$number"]}
      />,
    );
    expect(await screen.findByRole("heading", { name: "Commerce", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ines Moreau/ })).toHaveAttribute("href", "/people/p1");
    expect(screen.getByRole("link", { name: /1001/ })).toHaveAttribute("href", "/orders/o1");
    const box = screen.getByRole("searchbox");
    expect(box).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("link", { name: /Ines Moreau/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("link", { name: /1001/ })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(box).toHaveFocus();
    await userEvent.clear(box);
    await userEvent.type(box, "lamp{Enter}");
    expect(onQueryChange).toHaveBeenCalledWith("lamp");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("links a hit through its record link, then a route of the app", () => {
    const hit = { resource: "products", id: 7, title: "Lamp", subtitle: null, score: 1 };
    expect(searchHitHref(hit, ["/shop/products/$id"])).toBe("/shop/products/7");
    expect(searchHitHref(hit)).toBe("/products/7");
  });
});

describe("SignUpForm", () => {
  it("opens an account and asks to verify the email", async () => {
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/auth/register/`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json({ id: 9, email: "noor@example.com" }, { status: 201 });
      }),
    );
    const { container } = mount(<SignUpForm />, null);
    await userEvent.type(screen.getByLabelText("Your name"), "Noor Haddad");
    await userEvent.type(screen.getByLabelText("Email"), "noor@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase");
    expect(await axeViolations(container)).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Open an account" }));
    expect(await screen.findByText(/We sent a link to noor@example.com/)).toBeInTheDocument();
    expect(sent).toEqual([
      {
        email: "noor@example.com",
        password: "a long passphrase",
        first_name: "Noor",
        last_name: "Haddad",
      },
    ]);
  });

  it("says so when the project opens no account with a password", async () => {
    server.use(http.post(`${API}/auth/register/`, () => HttpResponse.json({}, { status: 404 })));
    mount(<SignUpForm />, null);
    await userEvent.type(screen.getByLabelText("Email"), "noor@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Open an account" }));
    expect(await screen.findByText(/does not open accounts with a password/)).toBeInTheDocument();
  });
});
