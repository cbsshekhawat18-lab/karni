/**
 * Wide models (experimental) against the backend's own OpenAPI document of a
 * 120-field product (./wide-fixtures): a MarkdownField's editor and preview,
 * its sanitized detail, field groups as sections and tabs in ResourceForm and
 * ResourceDetail, column sets in ResourceTable, and the render budgets.
 */
import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { axeViolations } from "../../../tests/axe";
import { server } from "../../../tests/msw/server";
import { createKarniClient } from "../../schema/client";
import { parseOpenApi } from "../../schema/parse";
import { KarniProvider } from "../../schema/provider";
import type { ParsedSchema, ResourceSchema } from "../../schema/types";
import { ResourceDetail } from "./detail/ResourceDetail";
import { ResourceForm } from "./form/ResourceForm";
import { markdownExcerpt } from "./markdown-field";
import { ResourceTable } from "./table/ResourceTable";
import { numbered, wideHandlers, wideOpenApi, wideProduct } from "./wide-fixtures";

/**
 * The render budgets of the 120-field product in this suite (jsdom, the
 * schema already loaded): ResourceForm in create mode until every field is in
 * the page, ResourceDetail until every value is (its row comes from msw).
 * Measured on 2026-10-31 on a shared 10-core Mac: the form 360 to 420 ms as
 * the first render of a test worker and 130 ms after it, the detail 70 to
 * 120 ms. The budgets leave room for a busy machine.
 */
const FORM_BUDGET_MS = 1000;
const DETAIL_BUDGET_MS = 600;

const ROWS = [wideProduct(1), wideProduct(2), wideProduct(3)];

function parsed(change?: (schema: ResourceSchema) => ResourceSchema): ParsedSchema {
  const all = parseOpenApi(wideOpenApi);
  const products = all.resources["products"];
  if (products === undefined) throw new Error("the wide schema has no products");
  return {
    ...all,
    resources: { ...all.resources, products: change ? change(products) : products },
  };
}

/**
 * The product with only `names` (and the groups and sets as published): the
 * interaction tests type and query through a few fields, not 120, so they
 * stay fast on a busy machine. The 120 fields are the budgets' (below).
 */
function only(...names: string[]): ParsedSchema {
  return parsed((schema) => ({
    ...schema,
    fields: schema.fields.filter((field) => names.includes(field.name)),
  }));
}

/** Queries over the 120-field page are slow in jsdom: a busy machine needs time. */
const SLOW = { timeout: 30_000 };

function mount(
  ui: React.ReactElement,
  schema: ParsedSchema = parsed(),
): ReturnType<typeof render> & { queryClient: QueryClient } {
  const client = createKarniClient({ baseUrl: "http://localhost/api" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(["karni", "$schema"], schema);
  const rendered = render(
    <KarniProvider client={client} queryClient={queryClient}>
      {ui}
    </KarniProvider>,
  );
  return { ...rendered, queryClient };
}

beforeEach(() => {
  server.use(...wideHandlers(ROWS));
  window.localStorage.clear();
});

describe("the wide schema", () => {
  it("parses a MarkdownField as text with format markdown, and the groups and sets", () => {
    const products = parsed().resources["products"];
    const overview = products?.fields.find((field) => field.name === "overview");
    expect(overview).toMatchObject({ kind: "text", format: "markdown", nullable: false });
    // A blank email or URL field is the same oneOf: a string that may be empty.
    expect(products?.fields.find((field) => field.name === "label_01")?.kind).toBe("string");
    expect(products?.fieldGroups?.layout).toBe("sections");
    expect(products?.fieldGroups?.groups.map((group) => group.label)).toEqual([
      "Overview",
      "Specifications",
      "Financials",
      "Content",
      "Measurements",
    ]);
    expect(products?.columnSets?.default).toBe("default");
    expect(products?.columnSets?.sets.map((found) => found.label)).toEqual([
      "Default",
      "Financial",
      "Logistics",
    ]);
    expect(products?.fields).toHaveLength(125);
  });

  it("turns markdown into a one-line excerpt for a table cell", () => {
    expect(markdownExcerpt("## Care\n\n- Wash **cold**\n- See [the guide](https://x.test)")).toBe(
      "Care Wash cold See the guide",
    );
  });
});

describe("a MarkdownField in ResourceForm", SLOW, () => {
  it("is edited with Write and Preview tabs, and the preview is sanitized", async () => {
    const user = userEvent.setup();
    mount(
      <ResourceForm resource="products" fieldGroups={false} />,
      only("name", "sku", "overview", "faq"),
    );
    const editor = screen.getByRole("tablist", { name: "Overview: write or preview" });
    const text = screen.getByLabelText("Overview");
    expect(text.tagName).toBe("TEXTAREA");
    fireEvent.change(text, {
      target: { value: '## Summary\n\nA **solid** frame.\n\n<img src="x" onerror="alert(1)">' },
    });
    await user.click(within(editor).getByRole("tab", { name: "Preview" }));
    const panel = screen.getByRole("tabpanel", { name: "Preview" });
    expect(await within(panel).findByRole("heading", { name: "Summary" })).toBeInTheDocument();
    expect(within(panel).getByText("solid").tagName).toBe("STRONG");
    // Raw HTML shows as text, never as an element with a handler.
    expect(panel.querySelector("img")).toBeNull();
    expect(panel).toHaveTextContent('<img src="x" onerror="alert(1)">');
    expect(text).not.toBeVisible();
    await user.click(within(editor).getByRole("tab", { name: "Write" }));
    expect(text).toBeVisible();
    expect(text).toHaveValue(
      '## Summary\n\nA **solid** frame.\n\n<img src="x" onerror="alert(1)">',
    );
  });

  it("opens Write and focuses the text when the field needs attention", async () => {
    const user = userEvent.setup();
    const required = parsed((schema) => ({
      ...schema,
      fields: schema.fields
        .filter((field) => ["name", "sku", "overview", "faq"].includes(field.name))
        .map((field) => (field.name === "faq" ? { ...field, required: true } : field)),
    }));
    mount(<ResourceForm resource="products" fieldGroups={false} />, required);
    await user.type(screen.getByLabelText(/^Name/), "Desk");
    await user.type(screen.getByLabelText(/^Sku/), "D-1");
    const editor = screen.getByRole("tablist", { name: "Faq: write or preview" });
    await user.click(within(editor).getByRole("tab", { name: "Preview" }));
    expect(screen.getByText("Nothing to preview yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create" }));
    const faq = screen.getByRole("textbox", { name: "Faq" });
    await waitFor(() => expect(faq).toHaveFocus());
    expect(within(editor).getByRole("tab", { name: "Write" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("field groups in ResourceForm", SLOW, () => {
  it("shows each group as a fieldset with its legend, the rest last under Other", () => {
    mount(<ResourceForm resource="products" />);
    const legends = Array.from(document.querySelectorAll("legend")).map(
      (legend) => legend.textContent,
    );
    expect(legends).toEqual([
      "Overview",
      "Specifications",
      "Financials",
      "Content",
      "Measurements",
      "Other",
    ]);
    const financials = screen.getByRole("group", { name: "Financials" });
    const inputs = within(financials)
      .getAllByRole("textbox")
      .map((input) => input.getAttribute("name"));
    expect(inputs).toEqual([...numbered("price", 6), ...numbered("rate", 4)]);
    const other = screen.getByRole("group", { name: "Other" });
    expect(within(other).getByLabelText("Label 28")).toBeInTheDocument();
    expect(within(other).queryByLabelText("Overview")).toBeNull();
  });

  it("as tabs, marks the tab of a failing field and opens it to focus the field", async () => {
    const user = userEvent.setup();
    mount(
      <ResourceForm
        resource="products"
        groupLayout="tabs"
        fieldGroups={[
          { label: "Codes", fields: ["sku"] },
          { label: "Naming", fields: ["name", "status"] },
        ]}
      />,
      only("name", "sku", "status", "grade", "label_01"),
    );
    const tabs = screen.getByRole("tablist", { name: "Product fields" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((tab) => tab.textContent),
    ).toEqual(["Codes", "Naming", "Other"]);
    expect(within(tabs).getByRole("tab", { name: "Codes" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // Closed tabs stay mounted (inputs registered) but hidden.
    expect(screen.getByLabelText(/^Name/)).not.toBeVisible();
    await user.type(screen.getByLabelText(/^Sku/), "D-1");
    await user.click(screen.getByRole("button", { name: "Create" }));
    const name = screen.getByLabelText(/^Name/);
    await waitFor(() => expect(name).toHaveFocus());
    const naming = within(tabs).getByRole("tab", { name: /^Naming/ });
    expect(naming).toHaveAttribute("aria-selected", "true");
    expect(naming).toHaveAccessibleName("Naming (1 field needs attention)");
  });

  it("shows one list with fieldGroups={false}", () => {
    mount(<ResourceForm resource="products" fieldGroups={false} />);
    expect(document.querySelectorAll("legend")).toHaveLength(0);
    expect(screen.queryByRole("tablist", { name: "Product fields" })).toBeNull();
  });
});

describe("ResourceDetail of a wide model", SLOW, () => {
  it("shows the groups as sections and markdown formatted", async () => {
    mount(<ResourceDetail resource="products" id={String(ROWS[0]?.["id"])} />);
    const overview = await screen.findByRole("region", { name: "Overview" });
    expect(
      within(overview).getByRole("heading", { name: "Overview of product 1" }),
    ).toBeInTheDocument();
    expect(within(overview).getAllByRole("link", { name: "link" })[0]).toHaveAttribute(
      "rel",
      "noopener noreferrer nofollow",
    );
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent)
      .filter((text) =>
        ["Overview", "Specifications", "Financials", "Content", "Measurements", "Other"].includes(
          text ?? "",
        ),
      );
    expect(headings).toEqual([
      "Overview",
      "Specifications",
      "Financials",
      "Content",
      "Measurements",
      "Other",
    ]);
    expect(
      within(screen.getByRole("region", { name: "Other" })).getByText("Label 28"),
    ).toBeVisible();
  });

  it("sanitizes markdown: no script, no event handler, raw HTML as text", async () => {
    const hostile: Record<string, unknown> = {
      ...wideProduct(9),
      care: '# Care\n\n<script>window.hacked = true</script>\n\n<img src="x" onerror="alert(1)">\n\n[click](javascript:alert(1))',
    };
    server.use(...wideHandlers([hostile]));
    mount(<ResourceDetail resource="products" id={String(hostile["id"])} />);
    const content = await screen.findByRole("region", { name: "Content" });
    expect(await within(content).findByRole("heading", { name: "Care" })).toBeInTheDocument();
    expect(content.querySelector("script")).toBeNull();
    expect(content.querySelector("img")).toBeNull();
    expect(content.querySelector("[onerror]")).toBeNull();
    expect(content.querySelector('a[href^="javascript"]')).toBeNull();
    expect(content).toHaveTextContent("<script>window.hacked = true</script>");
    expect((window as unknown as { hacked?: boolean }).hacked).toBeUndefined();
  });

  it("shows the groups as tabs with groupLayout='tabs'", async () => {
    const user = userEvent.setup();
    mount(<ResourceDetail resource="products" id={String(ROWS[0]?.["id"])} groupLayout="tabs" />);
    const tabs = await screen.findByRole("tablist", { name: "Product details" });
    expect(screen.getByText("Price 01")).not.toBeVisible();
    await user.click(within(tabs).getByRole("tab", { name: "Financials" }));
    expect(screen.getByText("Price 01")).toBeVisible();
  });
});

describe("column sets in ResourceTable", SLOW, () => {
  function headers(): string[] {
    return screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent?.trim() ?? "")
      .filter((text) => text !== "");
  }

  it("shows the default set and switches sets, remembered per user and table", async () => {
    const user = userEvent.setup();
    const { unmount } = mount(<ResourceTable resource="products" cardBreakpoint={0} />);
    await screen.findByText("Product 001");
    expect(headers()).toEqual(["Name", "Sku", "Brand", "Status", "Price 01"]);
    await user.click(screen.getByRole("button", { name: "Column set: Default" }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Financial" }));
    await waitFor(() =>
      expect(headers()).toEqual(
        ["Name", ...numbered("price", 6), ...numbered("rate", 4)].map(
          (name) => name.charAt(0).toUpperCase() + name.slice(1).replace("_", " "),
        ),
      ),
    );
    expect(window.localStorage.getItem("karni:table:column-set:products:anonymous")).toBe(
      "financial",
    );
    unmount();
    mount(<ResourceTable resource="products" cardBreakpoint={0} />);
    await screen.findByText("Product 001");
    expect(screen.getByRole("button", { name: "Column set: Financial" })).toBeInTheDocument();
    expect(headers()[1]).toBe("Price 01");
  });

  it("takes a controlled set, and columnSets={false} turns them off", async () => {
    const { unmount } = mount(
      <ResourceTable resource="products" cardBreakpoint={0} columnSet="logistics" />,
    );
    await screen.findByText("Product 001");
    expect(headers()).toEqual(["Name", "Dimension 01", "Dimension 02", "Dimension 03", "Date 01"]);
    unmount();
    mount(<ResourceTable resource="products" cardBreakpoint={0} columnSets={false} />);
    await screen.findByText("Product 001");
    expect(screen.queryByRole("button", { name: /^Column set/ })).toBeNull();
    // Every derived column but the markdown sections (long text is no column).
    expect(headers()).toContain("Label 28");
    expect(headers()).not.toContain("Overview");
  });
});

describe("accessibility of the groups", SLOW, () => {
  it("passes axe as form tabs and as detail sections", async () => {
    const form = mount(
      <ResourceForm
        resource="products"
        groupLayout="tabs"
        fieldGroups={[{ label: "Codes", fields: ["sku", "name", "overview"] }]}
      />,
    );
    expect(await axeViolations(form.container)).toEqual([]);
    form.unmount();
    const detail = mount(<ResourceDetail resource="products" id={String(ROWS[0]?.["id"])} />);
    await screen.findByRole("region", { name: "Overview" });
    await waitFor(async () => expect(await axeViolations(detail.container)).toEqual([]));
  });
});

describe("render budgets of the 120-field product", () => {
  // Cheap DOM queries only: *ByLabelText and *ByRole over 120 fields cost more than the render.
  function shown(field: string): boolean {
    return document.querySelector(`[data-karni-field="${field}"]`) !== null;
  }

  it(`ResourceForm renders within ${FORM_BUDGET_MS} ms`, () => {
    const started = performance.now();
    mount(<ResourceForm resource="products" />);
    const took = performance.now() - started;
    // Create mode with the schema loaded renders every field at once.
    expect(shown("label_28") && shown("faq") && shown("rate_04")).toBe(true);
    expect(document.querySelectorAll("[data-karni-field]")).toHaveLength(120);
    expect(took).toBeLessThan(FORM_BUDGET_MS);
  });

  it(`ResourceDetail renders within ${DETAIL_BUDGET_MS} ms`, async () => {
    const started = performance.now();
    mount(<ResourceDetail resource="products" id={String(ROWS[0]?.["id"])} />);
    await waitFor(() => expect(shown("label_28")).toBe(true));
    const took = performance.now() - started;
    expect(document.querySelectorAll("dl [data-karni-field]")).toHaveLength(125);
    expect(took).toBeLessThan(DETAIL_BUDGET_MS);
  });
});
