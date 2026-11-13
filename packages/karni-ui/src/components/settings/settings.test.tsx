/**
 * SettingsPage (details, sections, emails) and EmailTemplateEditor, against
 * a simulated `/preferences/` and `/email-templates/`.
 */
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../../../tests/msw/server";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import { EmailTemplateEditor } from "./EmailTemplateEditor";
import { SettingsPage } from "./SettingsPage";

function mount(ui: ReactNode) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
}

const PREFERENCES = {
  contract: 1,
  details: {
    values: { name: "Corner Shop", email: "hello@example.com", about: "", currency: "usd" },
    fields: [
      { name: "name", label: "Business name", type: "text", help: "Shown on invoices" },
      { name: "email", label: "Contact email", type: "email", help: "" },
      { name: "about", label: "About", type: "textarea", help: "" },
      {
        name: "currency",
        label: "Currency",
        type: "choice",
        help: "",
        choices: [
          { value: "usd", label: "US dollar" },
          { value: "eur", label: "Euro" },
        ],
      },
    ],
    locked: ["currency"],
    can_change: true,
  },
  sections: [
    {
      key: "shop",
      title: "Catalogue",
      describe: "How the catalogue behaves.",
      version: 1,
      schema: {
        properties: {
          track_stock: { type: "boolean", title: "Track stock", description: "Count units." },
          low_stock: { type: "integer", title: "Low stock level", minimum: 0, maximum: 100 },
        },
      },
      values: { track_stock: false, low_stock: 5 },
      defaults: { track_stock: false, low_stock: 5 },
      locked: [],
      can_change: true,
    },
  ],
  connections: { items: [], can_change: false },
  emails: {
    sender: { sender_name: "", sender_email: "", reply_to: "", from: "" },
    items: [
      {
        name: "commerce.order_paid",
        title: "Order paid",
        describe: "Sent when an order is paid.",
        audience: "the buyer",
        transactional: true,
        switchable: true,
        source: "commerce.order",
        default: true,
        on: true,
        locked: false,
      },
      {
        name: "accounts.login_code",
        title: "Sign-in code",
        describe: "The code to sign in.",
        audience: "the person signing in",
        transactional: true,
        switchable: false,
        source: "accounts.login",
        default: true,
        on: true,
        locked: false,
      },
    ],
    can_change: true,
  },
};

function servePreferences(): void {
  server.use(http.get("*/api/preferences/", () => HttpResponse.json(PREFERENCES)));
}

describe("SettingsPage", () => {
  it("shows a tab for the details, each section and the emails", async () => {
    servePreferences();
    mount(<SettingsPage />);
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Details", "Catalogue", "Emails"]);
    expect(screen.getByLabelText("Business name")).toHaveValue("Corner Shop");
    expect(screen.getByLabelText("Currency")).toBeDisabled();
    expect(screen.getByText("Fixed by the deployment")).toBeInTheDocument();
  });

  it("says so when the person may not change settings", async () => {
    server.use(
      http.get("*/api/preferences/", () => HttpResponse.json({ detail: "No." }, { status: 403 })),
    );
    mount(<SettingsPage />);
    expect(await screen.findByText("You may not change any setting.")).toBeInTheDocument();
  });

  it("sends only the changed detail and shows a field error", async () => {
    servePreferences();
    const bodies: unknown[] = [];
    server.use(
      http.patch("*/api/preferences/details/", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(
          { code: "invalid", detail: "Invalid", errors: { email: ["Enter a valid email."] } },
          { status: 400 },
        );
      }),
    );
    mount(<SettingsPage />);
    const email = await screen.findByLabelText("Contact email");
    await userEvent.clear(email);
    await userEvent.type(email, "nope");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Enter a valid email.")).toBeInTheDocument();
    expect(bodies).toEqual([{ email: "nope" }]);
  });

  it("sends a section's changed boolean and integer", async () => {
    servePreferences();
    const bodies: unknown[] = [];
    server.use(
      http.patch("*/api/preferences/sections/shop/", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({});
      }),
    );
    mount(<SettingsPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Catalogue" }));
    await userEvent.click(screen.getByLabelText("Track stock"));
    const level = screen.getByLabelText("Low stock level");
    await userEvent.clear(level);
    await userEvent.type(level, "9");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies).toEqual([{ track_stock: true, low_stock: 9 }]));
  });

  it("switches an email and groups by source", async () => {
    servePreferences();
    const bodies: unknown[] = [];
    server.use(
      http.patch("*/api/preferences/emails/commerce.order_paid/", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({});
      }),
    );
    mount(<SettingsPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Emails" }));
    expect(screen.getByText("The project's default sender")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Orders" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.getByText("Always sent")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: "Order paid" }));
    await waitFor(() => expect(bodies).toEqual([{ on: false }]));
  });
});

const TEMPLATE = {
  kind: "commerce.order_paid",
  title: "Order paid",
  describe: "Sent when an order is paid.",
  audience: "the buyer",
  switchable: true,
  on: true,
  fields: [
    { name: "order.number", meaning: "The order number" },
    { name: "lines.name", meaning: "Each line's name" },
  ],
  edited: false,
  subject: "Order {{ order.number }}",
  text: "Thanks",
  updated_at: null,
};

describe("EmailTemplateEditor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("loads, previews, saves and goes back to the default", async () => {
    let current = { ...TEMPLATE };
    const puts: unknown[] = [];
    server.use(
      http.get("*/api/email-templates/commerce.order_paid/", () => HttpResponse.json(current)),
      http.post("*/api/email-templates/commerce.order_paid/preview/", () =>
        HttpResponse.json({ subject: "Order 1001", text: "Thanks, Ada", html: "<p>x</p>" }),
      ),
      http.put("*/api/email-templates/commerce.order_paid/", async ({ request }) => {
        const body = (await request.json()) as { subject: string; text: string };
        puts.push(body);
        current = { ...current, ...body, edited: true };
        return HttpResponse.json(current);
      }),
      http.delete("*/api/email-templates/commerce.order_paid/", () => {
        current = { ...TEMPLATE };
        return HttpResponse.json(current);
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mount(<EmailTemplateEditor kind="commerce.order_paid" />);
    expect(await screen.findByLabelText("Subject")).toHaveValue("Order {{ order.number }}");
    expect(screen.getByText("{{ order.number }}")).toBeInTheDocument();
    expect(screen.getByText("The order number")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to the default" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Thanks, Ada")).toBeInTheDocument();
    expect(screen.getByText("Order 1001")).toBeInTheDocument();

    const text = screen.getByLabelText("Text");
    await userEvent.clear(text);
    await userEvent.type(text, "Hello");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(puts).toEqual([{ subject: "Order {{ order.number }}", text: "Hello" }]),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Back to the default" }));
    await waitFor(() => expect(screen.getByLabelText("Text")).toHaveValue("Thanks"));
    expect(screen.queryByRole("button", { name: "Back to the default" })).not.toBeInTheDocument();
  });

  it("shows a 400 error under the text", async () => {
    server.use(
      http.get("*/api/email-templates/commerce.order_paid/", () => HttpResponse.json(TEMPLATE)),
      http.put("*/api/email-templates/commerce.order_paid/", () =>
        HttpResponse.json({ text: ["Unknown field: {{ nope }}"] }, { status: 400 }),
      ),
    );
    mount(<EmailTemplateEditor kind="commerce.order_paid" />);
    await screen.findByLabelText("Text");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Unknown field: {{ nope }}")).toBeInTheDocument();
  });
});
