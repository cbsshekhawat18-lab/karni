import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { crc32 } from "node:zlib";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DataTable, compareValues, sortRows, type DataTableColumn } from "./data-table";
import { exportCell, exportFileName, toCsv } from "./export";
import { columnName, xlsxBytes } from "./xlsx";
import { axeViolations } from "../../../tests/axe";

interface Row {
  region: string;
  orders: number | null;
  opened: Date;
  active: boolean;
}

const rows: Row[] = [
  { region: "North", orders: 12, opened: new Date("2026-03-01"), active: true },
  { region: "south", orders: null, opened: new Date("2026-01-15"), active: false },
  { region: "East", orders: 3, opened: new Date("2026-02-10"), active: true },
  { region: "West", orders: 120, opened: new Date("2026-04-20"), active: false },
];

const columns: DataTableColumn<Row>[] = [
  { key: "region", header: "Region" },
  { key: "orders", header: "Orders" },
  { key: "opened", header: "Opened" },
  { key: "active", header: "Active", sortable: false },
];

function bodyRows(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("tbody tr[data-row]"));
}

function firstColumn(): string[] {
  return bodyRows().map((row) => row.querySelector("td")?.textContent ?? "");
}

/** The entries of a zip whose entries are stored, as xlsxBytes writes it. */
function unzipStored(bytes: Uint8Array): Map<string, { data: Uint8Array; crc: number }> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const entries = new Map<string, { data: Uint8Array; crc: number }>();
  let offset = 0;
  while (view.getUint32(offset, true) === 0x04034b50) {
    expect(view.getUint16(offset + 8, true)).toBe(0); // stored
    const crc = view.getUint32(offset + 14, true);
    const size = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const name = new TextDecoder().decode(bytes.slice(offset + 30, offset + 30 + nameLength));
    const start = offset + 30 + nameLength;
    entries.set(name, { data: bytes.slice(start, start + size), crc });
    offset = start + size;
  }
  expect(view.getUint32(offset, true)).toBe(0x02014b50); // the central directory follows
  return entries;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DataTable", () => {
  it("renders a captioned table with formatted cells and the empty dash", () => {
    render(<DataTable caption="Orders by region" columns={columns} rows={rows} />);
    const table = screen.getByRole("table", { name: "Orders by region" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Region", "Orders", "Opened", "Active"]);
    const west = bodyRows()[3];
    expect(west?.textContent).toContain("120");
    expect(west?.textContent).toContain("No");
    expect(bodyRows()[1]?.querySelectorAll("td")[1]?.textContent).toContain("empty");
    // numbers line up on the right
    expect(bodyRows()[0]?.querySelectorAll("td")[1]).toHaveClass("text-right");
  });

  it("sorts on a header click: ascending, descending, then as given; empty values last", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    render(
      <DataTable caption="Orders" columns={columns} rows={rows} onSortChange={onSortChange} />,
    );
    const orders = screen.getByRole("button", { name: "Orders" });
    await user.click(orders);
    expect(orders.closest("th")).toHaveAttribute("aria-sort", "ascending");
    expect(firstColumn()).toEqual(["East", "North", "West", "south"]);
    await user.click(orders);
    expect(orders.closest("th")).toHaveAttribute("aria-sort", "descending");
    expect(firstColumn()).toEqual(["West", "North", "East", "south"]);
    await user.click(orders);
    expect(orders.closest("th")).not.toHaveAttribute("aria-sort");
    expect(firstColumn()).toEqual(["North", "south", "East", "West"]);
    expect(onSortChange).toHaveBeenLastCalledWith(null);
    // text sorts naturally and case-insensitively, dates by time; an unsortable header is plain
    await user.click(screen.getByRole("button", { name: "Region" }));
    expect(firstColumn()).toEqual(["East", "North", "south", "West"]);
    await user.click(screen.getByRole("button", { name: "Opened" }));
    expect(firstColumn()).toEqual(["south", "East", "North", "West"]);
    expect(screen.queryByRole("button", { name: "Active" })).not.toBeInTheDocument();
  });

  it("keeps its header and first column in view (sticky)", () => {
    render(<DataTable caption="Orders" columns={columns} rows={rows} />);
    expect(document.querySelector("thead")).toHaveClass("sticky", "top-0");
    expect(screen.getByRole("columnheader", { name: "Region" })).toHaveClass("sticky", "left-0");
    expect(bodyRows()[0]?.querySelector("td")).toHaveClass("sticky", "left-0");
    expect(screen.getByRole("region", { name: "Orders" })).toHaveAttribute("tabindex", "0");
  });

  it("renders 10,000 rows as a window of rows, quickly, and moves the window on scroll", () => {
    const many = Array.from({ length: 10_000 }, (_, index) => ({
      sku: `SKU-${String(index).padStart(5, "0")}`,
      stock: (index * 37) % 500,
    }));
    const started = performance.now();
    render(
      <DataTable
        caption="Catalog"
        columns={[
          { key: "sku", header: "SKU" },
          { key: "stock", header: "Stock" },
        ]}
        rows={many}
      />,
    );
    const elapsed = performance.now() - started;
    console.info(`DataTable: 10,000 rows rendered in ${elapsed.toFixed(0)} ms (jsdom)`);
    expect(elapsed).toBeLessThan(1500);
    const table = screen.getByRole("table", { name: "Catalog" });
    expect(table).toHaveAttribute("aria-rowcount", "10001");
    expect(bodyRows().length).toBeGreaterThan(10);
    expect(bodyRows().length).toBeLessThan(60);
    expect(bodyRows()[0]).toHaveAttribute("aria-rowindex", "2");

    const box = screen.getByRole("region", { name: "Catalog" });
    Object.defineProperty(box, "scrollTop", { configurable: true, value: 40 * 5000 });
    fireEvent.scroll(box);
    expect(firstColumn()).toContain("SKU-05000");
    expect(firstColumn()).not.toContain("SKU-00000");
    expect(bodyRows().length).toBeLessThan(60);
  });

  it("renders every row with virtualize={false}", () => {
    const many = Array.from({ length: 150 }, (_, index) => ({ n: index }));
    render(
      <DataTable
        caption="All"
        columns={[{ key: "n", header: "N" }]}
        rows={many}
        virtualize={false}
      />,
    );
    expect(bodyRows()).toHaveLength(150);
    expect(screen.getByRole("table")).not.toHaveAttribute("aria-rowcount");
  });

  it("exports CSV and XLSX of every row in the order shown", async () => {
    const user = userEvent.setup();
    const blobs: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      blobs.push(blob as Blob);
      return "blob:test";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      names.push(this.download);
    });
    render(
      <DataTable
        caption="Orders by region"
        columns={columns}
        rows={rows}
        initialSort={{ key: "orders", direction: "desc" }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Export Orders by region as CSV" }));
    await waitFor(() => expect(blobs).toHaveLength(1));
    const csvBytes = new Uint8Array(await (blobs[0] as Blob).arrayBuffer());
    expect([...csvBytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]); // the UTF-8 byte order mark
    const csv = new TextDecoder().decode(csvBytes);
    expect(names[0]).toBe("orders-by-region.csv");
    expect(csv.split("\r\n").slice(0, 3)).toEqual([
      "Region,Orders,Opened,Active",
      "West,120,2026-04-20T00:00:00.000Z,false",
      "North,12,2026-03-01T00:00:00.000Z,true",
    ]);
    await user.click(screen.getByRole("button", { name: "Export Orders by region as XLSX" }));
    await waitFor(() => expect(blobs).toHaveLength(2));
    expect(names[1]).toBe("orders-by-region.xlsx");
    const bytes = new Uint8Array(await (blobs[1] as Blob).arrayBuffer());
    const sheet = new TextDecoder().decode(
      unzipStored(bytes).get("xl/worksheets/sheet1.xml")?.data,
    );
    expect(sheet).toContain(
      '<c r="A2" t="inlineStr"><is><t xml:space="preserve">West</t></is></c>',
    );
    expect(sheet).toContain('<c r="B2"><v>120</v></c>');
  });

  it("shows loading, empty and error states", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(<DataTable caption="Orders" columns={columns} rows={[]} loading />);
    expect(screen.getByRole("region", { name: "Orders" })).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("button", { name: /Export/ })).not.toBeInTheDocument();
    rerender(<DataTable caption="Orders" columns={columns} rows={[]} emptyLabel="No orders." />);
    expect(screen.getByText("No orders.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export Orders as CSV" })).toBeDisabled();
    rerender(
      <DataTable
        caption="Orders"
        columns={columns}
        rows={[]}
        error={new TypeError("Failed to fetch")}
        onRetry={onRetry}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("opens a row from its first cell, by click or keyboard", async () => {
    const onRowClick = vi.fn();
    render(<DataTable caption="Orders" columns={columns} rows={rows} onRowClick={onRowClick} />);
    await userEvent.click(screen.getByRole("button", { name: "East" }));
    expect(onRowClick).toHaveBeenCalledWith(rows[2]);
  });

  it("passes axe, small and virtualized", async () => {
    const { container, unmount } = render(
      <DataTable caption="Orders" columns={columns} rows={rows} />,
    );
    expect(await axeViolations(container)).toEqual([]);
    unmount();
    const many = Array.from({ length: 500 }, (_, index) => ({ n: index, label: `Row ${index}` }));
    const big = render(
      <DataTable
        caption="Many"
        columns={[
          { key: "label", header: "Label" },
          { key: "n", header: "N" },
        ]}
        rows={many}
      />,
    );
    expect(await axeViolations(big.container)).toEqual([]);
  });
});

describe("DataTable helpers", () => {
  it("compares values: numbers, dates, booleans, natural text, empty last", () => {
    expect(compareValues(2, 10)).toBeLessThan(0);
    expect(compareValues("item 2", "item 10")).toBeLessThan(0);
    expect(compareValues("b", "A")).toBeGreaterThan(0);
    expect(compareValues(null, 1)).toBeGreaterThan(0);
    expect(compareValues(false, true)).toBeLessThan(0);
    expect(compareValues(new Date(1), new Date(2))).toBeLessThan(0);
  });

  it("sorts stably and leaves rows alone without a sort or a known column", () => {
    const data = [
      { k: 1, n: "a" },
      { k: 1, n: "b" },
      { k: 0, n: "c" },
    ];
    const cols: DataTableColumn<(typeof data)[number]>[] = [{ key: "k", header: "K" }];
    expect(sortRows(data, cols, { key: "k", direction: "asc" }).map((r) => r.n)).toEqual([
      "c",
      "a",
      "b",
    ]);
    expect(sortRows(data, cols, null)).toBe(data);
    expect(sortRows(data, cols, { key: "missing", direction: "asc" })).toBe(data);
  });

  it("writes RFC 4180 CSV that a spreadsheet will not run as a formula", () => {
    const csv = toCsv(
      ["Name", "Note", "Amount"],
      [
        ["Rake, large", 'Said "hi"', 12.5],
        ["=HYPERLINK(1)", "+1", -4],
        ["@sum", "line\nbreak", null],
      ],
    );
    expect(csv).toBe(
      "﻿Name,Note,Amount\r\n" +
        '"Rake, large","Said ""hi""",12.5\r\n' +
        "'=HYPERLINK(1),'+1,-4\r\n" +
        `'@sum,"line\nbreak",\r\n`,
    );
    expect(exportFileName("Revenue by région!", "csv")).toBe("revenue-by-region.csv");
    expect(exportFileName("", "xlsx")).toBe("table.xlsx");
    expect(exportCell(new Date("2026-01-02T03:04:05Z"))).toBe("2026-01-02T03:04:05.000Z");
    expect(exportCell(undefined)).toBeNull();
  });

  it("writes an XLSX zip with valid CRCs, typed cells, a bold frozen header and safe XML", () => {
    const bytes = xlsxBytes(
      "Orders: Q1/Q2",
      ["Region", "Orders", "Active"],
      [
        ['North <&> "East"', 12, true],
        ["bad\u0001char", Number.NaN, null],
      ],
    );
    const entries = unzipStored(bytes);
    expect([...entries.keys()]).toEqual([
      "[Content_Types].xml",
      "_rels/.rels",
      "xl/workbook.xml",
      "xl/_rels/workbook.xml.rels",
      "xl/styles.xml",
      "xl/worksheets/sheet1.xml",
    ]);
    for (const { data, crc } of entries.values()) expect(crc).toBe(crc32(data));
    const text = (name: string): string => new TextDecoder().decode(entries.get(name)?.data);
    expect(text("xl/workbook.xml")).toContain('<sheet name="Orders  Q1 Q2" sheetId="1"');
    const sheet = text("xl/worksheets/sheet1.xml");
    expect(sheet).toContain('<c r="A1" s="1" t="inlineStr"><is><t xml:space="preserve">Region</t>');
    expect(sheet).toContain("North &lt;&amp;&gt; &quot;East&quot;");
    expect(sheet).toContain('<c r="B2"><v>12</v></c><c r="C2" t="b"><v>1</v></c>');
    expect(sheet).toContain("badchar");
    expect(sheet).toContain('<c r="B3" t="inlineStr"><is><t xml:space="preserve">NaN</t>');
    expect(sheet).toContain('state="frozen"');
    // the same rows give the same bytes
    expect(xlsxBytes("x", ["a"], [[1]])).toEqual(xlsxBytes("x", ["a"], [[1]]));
    expect([0, 25, 26, 701, 702].map(columnName)).toEqual(["A", "Z", "AA", "ZZ", "AAA"]);
  });
});
