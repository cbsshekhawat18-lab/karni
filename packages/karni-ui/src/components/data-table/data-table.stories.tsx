import type { Meta, StoryObj } from "@storybook/react";
import { DataTable, type DataTableColumn } from "./data-table";

interface RegionRow {
  region: string;
  orders: number;
  revenue: number;
  share: number;
}

const regions: RegionRow[] = [
  { region: "North", orders: 1204, revenue: 48210.5, share: 0.34 },
  { region: "South", orders: 860, revenue: 31004, share: 0.22 },
  { region: "East", orders: 412, revenue: 15870.25, share: 0.11 },
  { region: "West", orders: 1101, revenue: 44012, share: 0.33 },
];

const columns: DataTableColumn<RegionRow>[] = [
  { key: "region", header: "Region" },
  { key: "orders", header: "Orders" },
  {
    key: "revenue",
    header: "Revenue",
    format: (value) =>
      typeof value === "number"
        ? value.toLocaleString(undefined, { style: "currency", currency: "EUR" })
        : "",
  },
  {
    key: "share",
    header: "Share",
    format: (value) => (typeof value === "number" ? `${Math.round(value * 100)}%` : ""),
  },
];

interface ProductRow {
  sku: string;
  name: string;
  category: string;
  stock: number;
  price: number;
}

const categories = ["Tools", "Garden", "Kitchen", "Toys", "Books"];

/** 10,000 rows of a product catalog, computed (no request). */
export function manyProducts(count = 10_000): ProductRow[] {
  return Array.from({ length: count }, (_, index) => ({
    sku: `SKU-${String(index + 1).padStart(5, "0")}`,
    name: `Product ${index + 1}`,
    category: categories[index % categories.length] ?? "Tools",
    stock: (index * 37) % 500,
    price: Math.round(((index * 13) % 9000) + 99) / 100,
  }));
}

const productColumns: DataTableColumn<ProductRow>[] = [
  { key: "sku", header: "SKU" },
  { key: "name", header: "Name" },
  { key: "category", header: "Category" },
  { key: "stock", header: "Stock" },
  { key: "price", header: "Price" },
];

const meta = {
  title: "Blocks/DataTable",
  component: DataTable<RegionRow>,
  tags: ["autodocs"],
  args: { caption: "Orders by region", columns, rows: regions },
} satisfies Meta<typeof DataTable<RegionRow>>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A computed summary: sort by any header, export CSV or XLSX. */
export const Summary: Story = {};

/** Sorted by revenue, highest first, from the start. */
export const Sorted: Story = { args: { initialSort: { key: "revenue", direction: "desc" } } };

/** 10,000 rows: only the rows in view are in the page, and it scrolls smoothly. */
export const TenThousandRows: Story = {
  render: () => (
    <DataTable caption="Product catalog" columns={productColumns} rows={manyProducts()} />
  ),
};

export const Loading: Story = { args: { loading: true } };

export const Empty: Story = { args: { rows: [] } };
